# Vendor Patches

Patches applied to local vendor/ clones that are not submodules and not tracked by git.
Re-apply after a fresh `git clone` of the upstream repo.

---

## PX4-Autopilot — gz-transport13 NAMES fix

**File:** `src/modules/simulation/gz_bridge/CMakeLists.txt`

**Upstream version:** PX4 v1.14.3 (tag `v1.14.3`)

**Context:** PX4 v1.14.3 searches for `gz-transport12` (Gazebo Garden) but Homebrew
`gz-harmonic` (Gazebo Harmonic 8.x) ships `gz-transport13`. Without this patch,
`find_package(gz-transport)` returns `gz-transport_FOUND=FALSE`, the `gz_x500` sim
target is never registered, and `make px4_sitl gz_x500` fails with
`No rule to make target 'gz_x500'`.

**Diff:**

```diff
--- a/src/modules/simulation/gz_bridge/CMakeLists.txt
+++ b/src/modules/simulation/gz_bridge/CMakeLists.txt
@@ -34,7 +34,8 @@
 find_package(gz-transport
 	#REQUIRED COMPONENTS core
 	NAMES
 		#ignition-transport11 # IGN (Fortress and earlier) no longer supported
 		gz-transport12
+		gz-transport13
 	#QUIET
 )
```

**Re-apply:**

```bash
cd vendor/PX4-Autopilot/src/modules/simulation/gz_bridge
sed -i '' '/gz-transport12/a\\t\tgz-transport13' CMakeLists.txt
# Verify:
grep "gz-transport1" CMakeLists.txt
```

**Also required at build time:** `CMAKE_PREFIX_PATH=/opt/homebrew` so cmake can
locate `/opt/homebrew/lib/cmake/gz-transport13/`.
