import Lean

open Lean

namespace LeanDag

structure Context where
  env : Environment

def Context.find? (ctx : Context) (name : Name) : Option ConstantInfo :=
  ctx.env.checked.get.find? name

def isTheorem (info : ConstantInfo) : Bool :=
  match info with
  | .thmInfo _ => true
  | _ => false

-- Compiler-generated proof helpers belong to their enclosing declaration.
def isNode (info : ConstantInfo) : Bool :=
  isTheorem info && !(privateToUserName info.name).isInternalDetail

structure Uses where
  visited : NameSet := {}
  nodes : NameSet := {}
  sorryFound : Bool := false
  missing : NameSet := {}

-- Labeled sorries encode source locations as Lean.Name values. Those labels
-- reference implementation code, not mathematical premises of the proof.
partial def stripSorryLabels (expr : Expr) : Expr :=
  expr.replace fun e => do
    let _ ← Meta.isLabeledSorry? e
    let .forallE _ _ body _ := e.getArg! 0 | none
    let type := body.instantiate1 (e.getArg! 2)
    let plain := mkApp2 e.getAppFn type (e.getArg! 1)
    some <| stripSorryLabels <| mkAppN plain (e.getAppArgs.extract 3 e.getAppNumArgs)

def usedConstants (expr : Expr) : Array Name :=
  (stripSorryLabels expr).getUsedConstants

partial def visit (ctx : Context) (root name : Name) : StateM Uses Unit := do
  if (← get).visited.contains name then return
  modify fun s => { s with visited := s.visited.insert name }
  if name == ``sorryAx then
    modify fun s => { s with sorryFound := true }
    return
  -- Imported declarations form the boundary of a file-local graph.
  if ctx.env.isImportedConst name then return
  let some info := ctx.find? name | do
    modify fun s => { s with missing := s.missing.insert name }
    return
  if name != root && isNode info then
    modify fun s => { s with nodes := s.nodes.insert name }
    return
  for c in usedConstants info.type do visit ctx root c
  if let some value := info.value? (allowOpaque := true) then
    for c in usedConstants value do visit ctx root c
  if let .inductInfo value := info then
    for c in value.ctors do visit ctx root c

def collect (ctx : Context) (root : Name) (expr : Expr) : Uses := Id.run do
  let mut state : Uses := { visited := ({} : NameSet).insert root }
  for c in usedConstants expr do
    state := (visit ctx root c).run state |>.2
  return state

def namesJson (names : NameSet) : Json :=
  toJson (names.toArray.map Name.toString |>.qsort (· < ·))

def resolveTarget (ctx : Context) (requested : String) : IO Name := do
  let exact := requested.toName
  if let some info := ctx.env.checked.get.find? exact then
    if isTheorem info && !(ctx.env.isImportedConst exact) then return exact
  let candidates := ctx.env.checked.get.constants.fold (init := #[]) fun acc name info =>
    let visible := (privateToUserName name).toString
    if isTheorem info && !(ctx.env.isImportedConst name) &&
        (visible == requested || visible.endsWith ("." ++ requested)) then
      acc.push name
    else acc
  match candidates.toList with
  | [name] => return name
  | [] => throw <| IO.userError s!"Theorem '{requested}' was not found in the input file. Use its fully qualified name."
  | _ => throw <| IO.userError s!"Ambiguous theorem '{requested}': {candidates.toList.map Name.toString}. Use its fully qualified name."

def nodeJson (ctx : Context) (name : Name) (inputFile : String) : CoreM (Json × Array Name) := do
  let some info := ctx.find? name | throwError "Missing declaration: {name}"
  let statement := collect ctx name info.type
  let proof := (info.value? (allowOpaque := true)).map (collect ctx name) |>.getD {}
  let missing := statement.missing ++ proof.missing
  unless missing.isEmpty do throwError "Dependency declarations unavailable: {missing.toArray}"
  let moduleName := ctx.env.mainModule
  let location ← findDeclarationRanges? name
  let locationJson := match location with
    | some r => json% { "line": $(r.range.pos.line), "column": $(r.range.pos.column),
        "end_line": $(r.range.endPos.line), "end_column": $(r.range.endPos.column) }
    | none => Json.null
  let typeText ← Meta.MetaM.toIO (do return (← Meta.ppExpr info.type).pretty)
    { fileName := inputFile, fileMap := default } { env := ctx.env }
    {} {}
  let hasDirectSorry := info.type.hasSorry ||
    ((info.value? (allowOpaque := true)).map Expr.hasSorry |>.getD false)
  let data := json% {
    "id": $(name.toString), "name": $((privateToUserName name).toString),
    "kind": "theorem",
    "module": $(moduleName.toString), "file": $(inputFile), "location": $(locationJson),
    "statement": $(typeText.1),
    "direct_sorry": $(hasDirectSorry),
    "has_sorry": $(statement.sorryFound || proof.sorryFound),
    "statement_sorry": $(statement.sorryFound), "proof_sorry": $(proof.sorryFound),
    "statement_dependencies": $(namesJson statement.nodes),
    "proof_dependencies": $(namesJson proof.nodes)
  }
  return (data, (statement.nodes ++ proof.nodes).toArray)

def extract (ctx : Context) (root : Name) (inputFile : String) (maxNodes : Nat) : CoreM Json := do
  let mut pending := #[root]
  let mut visited : NameSet := {}
  let mut nodes : Array Json := #[]
  while !pending.isEmpty do
    let name := pending.back!
    pending := pending.pop
    if visited.contains name then continue
    if visited.size >= maxNodes then
      throwError "Graph exceeds {maxNodes} nodes. Increase --max-nodes; no partial graph was exported."
    visited := visited.insert name
    let (node, deps) ← nodeJson ctx name inputFile
    nodes := nodes.push node
    pending := pending ++ deps
  return json% { "schema_version": 1, "lean_version": $(Lean.versionString),
    "scope": "input_file", "sorry_scope": "input_file",
    "root": $(root.toString), "input_file": $(inputFile), "nodes": $(nodes) }

end LeanDag

unsafe def main (args : List String) : IO UInt32 := do
  try
    let [inputFile, theoremName, outputFile, setupFile, maxNodesText] := args
      | throw <| IO.userError "Expected: FILE THEOREM OUTPUT SETUP_OR_DASH MAX_NODES"
    let some maxNodes := maxNodesText.toNat? | throw <| IO.userError "Invalid node limit"
    initSearchPath (← findSysroot)
    enableInitializersExecution
    let setup? ← if setupFile == "-" then pure none else some <$> ModuleSetup.load setupFile
    let input ← IO.FS.readFile inputFile
    let options := ({} : Options).setBool `Elab.async false
    let moduleName := setup?.map (·.name) |>.getD
      (((System.FilePath.mk inputFile).fileStem.getD "Input").toName)
    let some env ← Elab.runFrontend input options inputFile moduleName (setup? := setup?)
      | throw <| IO.userError "Input file failed Lean checking. Explicit sorry is supported; elaboration errors are not."
    let ctx : LeanDag.Context := { env }
    let root ← LeanDag.resolveTarget ctx theoremName
    let (result, _) ← (LeanDag.extract ctx root inputFile maxNodes).toIO
      { fileName := inputFile, fileMap := FileMap.ofString input,
        options := options.setNat `maxRecDepth 16384 |>.setNat `maxHeartbeats 0 }
      { env }
    IO.FS.writeFile outputFile result.pretty
    return (0 : UInt32)
  catch e =>
    IO.eprintln s!"lean-dag: {e}"
    return (1 : UInt32)
