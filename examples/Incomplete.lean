namespace Demo

theorem unfinished (n : Nat) : n + 0 = n := by
  sorry

theorem finished (n : Nat) : 0 + n = n := by
  exact Nat.zero_add n

theorem intermediate (n : Nat) : n + 0 = n := by
  exact unfinished n

theorem target (n : Nat) : n + 0 = 0 + n := by
  have h := intermediate n
  exact h.trans (finished n).symm

end Demo
