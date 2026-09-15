module

public section

namespace Imported

theorem missing (n : Nat) : n + 0 = n := by sorry

theorem chain (n : Nat) : n + 0 = n := missing n

theorem clean (n : Nat) : 0 + n = n := Nat.zero_add n

end Imported
