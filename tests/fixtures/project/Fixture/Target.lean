module

import Fixture.Imported

public theorem imported_target (n : Nat) : n + 0 = 0 + n :=
  (Imported.chain n).trans (Imported.clean n).symm

namespace Imported

public theorem local_missing (n : Nat) : n + 0 = n := by sorry

public theorem local_target (n : Nat) : n + 0 = 0 + n :=
  (local_missing n).trans (clean n).symm

end Imported
