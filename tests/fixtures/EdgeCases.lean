namespace Cases

theorem missing : True := by sorry

def proofHelper : True := missing

def sorryHelper : True := by sorry

private theorem privateLemma : True := missing

axiom assumption : True

theorem through_definition : True := proofHelper

theorem through_sorry_definition : True := sorryHelper

theorem through_private : True := privateLemma

theorem through_axiom : True := assumption

theorem unfinished_target : True := by sorry

theorem sorry_statement : (sorry : Prop) := by sorry

def fromProof (_h : True) : Prop := True

theorem statement_dependency : fromProof missing := True.intro

theorem unused : True := True.intro

namespace One
theorem duplicate : True := True.intro
end One

namespace Two
theorem duplicate : True := True.intro
end Two

end Cases
