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

structure Certificate where
  proposition : Prop
  proof : proposition

structure WrappedNat where
  value : Nat

theorem through_constructor_injectivity (a b : Nat) (h : a = b) :
    WrappedNat.mk a = WrappedNat.mk b := by
  rw [WrappedNat.mk.injEq]
  exact h

structure DerivedCertificate extends Certificate where
  extra : True

class HasCertificate where
  proof : True

class HasDerivedCertificate extends HasCertificate where
  extra : True

theorem through_projection (c : Certificate) : c.proposition := c.proof

theorem through_inherited_projection (c : DerivedCertificate) : c.proposition := c.proof

theorem through_class_projection [HasDerivedCertificate] : True := HasCertificate.proof

structure ProofBox where
  proof : True

def boxWithDependency : ProofBox := { proof := missing }
def boxWithSorry : ProofBox := { proof := by sorry }
def boxWithAxiom : ProofBox := { proof := assumption }

theorem through_box_dependency : True := boxWithDependency.proof
theorem through_box_sorry : True := boxWithSorry.proof
theorem through_box_axiom : True := boxWithAxiom.proof

structure DependentBox where
  proof : fromProof missing

theorem through_projection_type (b : DependentBox) : True := b.proof

namespace Named
theorem proof : True := True.intro
end Named

namespace One
theorem duplicate : True := True.intro
end One

namespace Two
theorem duplicate : True := True.intro
end Two

end Cases
