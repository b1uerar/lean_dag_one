import Lean

open Lean

def resolveName (env : Environment) (requested : String) : IO Name := do
  if env.contains requested.toName then return requested.toName
  let names := env.constants.fold (init := #[]) fun acc name _ =>
    if (privateToUserName name).toString == requested then acc.push name else acc
  if names.size == 1 then return names[0]!
  throw <| IO.userError s!"Unknown or ambiguous theorem: {requested}"

unsafe def main (args : List String) : IO UInt32 := do
  try
    let [inputFile, setupFile, requestFile] := args
      | throw <| IO.userError "Expected SOURCE SETUP REQUEST"
    initSearchPath (← findSysroot)
    enableInitializersExecution
    let setup ← ModuleSetup.load setupFile
    let source ← IO.FS.readFile inputFile
    let request ← IO.ofExcept <| Json.parse (← IO.FS.readFile requestFile)
    let some env ← Elab.runFrontend source
        (({} : Options).setBool `Elab.async false) inputFile setup.name (setup? := some setup)
      | throw <| IO.userError "Source failed Lean checking"
    let mode ← IO.ofExcept <| request.getObjValAs? String "mode"
    if mode == "parse" then
      let terms ← IO.ofExcept <| request.getObjValAs? (Array String) "terms"
      for term in terms do
        let _ ← IO.ofExcept <| Parser.runParserCategory env `term term
      IO.println "{\"success\":true}"
    else if mode == "compare" then
      let candidate ← IO.ofExcept <| request.getObjValAs? String "candidate"
      let target ← IO.ofExcept <| request.getObjValAs? String "target"
      let some extracted ← Elab.runFrontend candidate
          (({} : Options).setBool `Elab.async false) inputFile setup.name (setup? := some setup)
        | throw <| IO.userError "Extracted context failed Lean checking"
      let _ ← resolveName extracted target
      let localNames := extracted.constants.fold (init := #[]) fun acc name _ =>
        if extracted.isImportedConst name then acc else acc.push name
      -- mkAuxLemma caches by type; its names and count depend on earlier commands.
      let auxiliary := (Meta.auxLemmasExt.getState extracted).lemmas.foldl
        (fun names _ entry => names.insert entry.1) ({} : NameSet)
      for name in localNames do
        let some actual := extracted.find? name
          | throw <| IO.userError s!"Missing extracted declaration: {name}"
        if auxiliary.contains name then
          if let .thmInfo _ := actual then continue
        let some expected := env.find? name
          | throw <| IO.userError s!"Extraction added a declaration: {name}"
        let sameValue := match expected, actual with
          | .thmInfo _, .thmInfo _ => true
          | _, _ => expected.value? (allowOpaque := true) == actual.value? (allowOpaque := true)
        unless expected.levelParams == actual.levelParams &&
            expected.type == actual.type && sameValue do
          throw <| IO.userError s!"Extraction changed a declaration: {name}"
      -- Proof irrelevance permits different proof terms, never additional axioms.
      -- Share the visited set so common Mathlib dependencies are traversed only once.
      let (_, axioms) := ((localNames.forM CollectAxioms.collect).run extracted).run {}
      for ax in axioms.axioms do
        unless #[``propext, ``Classical.choice, ``Quot.sound].contains ax do
          throw <| IO.userError s!"Extraction uses untrusted axiom: {ax}"
      IO.println "{\"success\":true}"
    else if mode == "refute" || mode == "prove" then
      let targetText ← IO.ofExcept <| request.getObjValAs? String "target"
      let target ← resolveName env targetText
      let checkKind := if mode == "refute" then "Refutation" else "Proof"
      let refuter ← if mode == "refute" then do
        let text ← IO.ofExcept <| request.getObjValAs? String "refuter"
        try resolveName env text
        catch error =>
          -- Accept the conventional short name in the target's namespace too.
          let targetNamespace := (privateToUserName target).getPrefix
          if targetNamespace.isAnonymous || !text.toName.getPrefix.isAnonymous then throw error
          resolveName env (targetNamespace ++ text.toName).toString
        else pure target
      let (valid, _) ← (do
        let targetExpr ← Meta.mkConstWithFreshMVarLevels target
        let refuterExpr ← Meta.mkConstWithFreshMVarLevels refuter
        let targetType ← Meta.inferType targetExpr
        let refuterType ← Meta.inferType refuterExpr
        unless ← Meta.isProp targetType do throwError "Target is not a proposition"
        if mode == "refute" then
          unless ← Meta.isDefEq refuterType (mkApp (mkConst ``Not) targetType) do
            throwError "Refutation must negate the entire, exact target type"
        let axioms ← collectAxioms refuter
        for ax in axioms do
          unless #[``propext, ``Classical.choice, ``Quot.sound].contains ax do
            throwError "{checkKind} uses untrusted axiom: {ax}"
        pure true : MetaM Bool).toIO
          { fileName := inputFile, fileMap := FileMap.ofString source }
          { env } {} {}
      unless valid do throw <| IO.userError s!"{checkKind} validation failed"
      IO.println "{\"success\":true}"
    else
      throw <| IO.userError "Unknown task check mode"
    return (0 : UInt32)
  catch e =>
    IO.eprintln s!"dag-task-check: {e}"
    return (1 : UInt32)
