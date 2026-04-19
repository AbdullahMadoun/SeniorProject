# Vendor Patches

Patches applied to local vendor/ clones that are not submodules and not tracked by git.

> **STATUS (2026-04-19): The native macOS PX4 build path is SUPERSEDED.**
> The team's Docker SITL path (`deploy/simulation/Dockerfile` + `docker-compose.simulation.yml`,
> merged from origin/main in commit `c71213e`) builds PX4 v1.14.3 inside an Ubuntu 22.04
> container where gz-transport12 is native. The patch below is no longer applied to any
> active build pipeline — it is preserved here as a research record.

---

## [SUPERSEDED] PX4-Autopilot — gz-transport13 NAMES fix for native macOS build

**Status:** Superseded by Docker SITL path. Patch still applied to the local
`vendor/PX4-Autopilot` clone on disk but has no effect on the Docker build.

**File:** `src/modules/simulation/gz_bridge/CMakeLists.txt`

**Upstream version:** PX4 v1.14.3 (tag `v1.14.3`)

### Why this was attempted

Goal was to run PX4 SITL natively on macOS (Apple Silicon, Darwin 25.4.0) with
Gazebo Harmonic installed via Homebrew (`gz-harmonic` formula, gz-sim 8.11.0).

### Root cause of failure

PX4 v1.14.3 is authored against Ubuntu 22.04 + Gazebo Garden. Its cmake build
searches for `gz-transport12` (Garden) via:

```cmake
find_package(gz-transport NAMES gz-transport12)
```

Homebrew `gz-harmonic` ships `gz-transport13` (Harmonic). Without the patch,
`find_package(gz-transport)` returns `gz-transport_FOUND=FALSE`, the `gz_x500`
sim target is never registered, and `make px4_sitl gz_x500` fails with:

```
gmake[1]: *** No rule to make target 'gz_x500'. Stop.
```

### Patch applied (commit 5ddeaa1)

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

Also required at build time: `CMAKE_PREFIX_PATH=/opt/homebrew`.

### Why it was abandoned

The transport-version mismatch is a symptom of deeper PX4-on-macOS
incompatibility: PX4 v1.14.3's cmake layer, ubuntu.sh dependency bootstrap, and
Gazebo plugin ABI are all authored against Ubuntu 22.04 toolchains. Continuing
native Mac would require patching multiple cmake files and risked runtime plugin
ABI mismatches beyond what was practical to debug.

The team simultaneously landed a Docker SITL path (`deploy/simulation/Dockerfile`,
commits `7831336` + `aba4f02`) that solves the problem cleanly: the image builds
PX4 v1.14.3 on Ubuntu 22.04 inside the container, where the toolchain matches
upstream assumptions. Decision made to pivot in R9-Docker-Pivot phase (2026-04-19).

### Re-apply instructions (if native build is ever revisited)

```bash
cd vendor/PX4-Autopilot/src/modules/simulation/gz_bridge
sed -i '' '/gz-transport12/a\\t\tgz-transport13' CMakeLists.txt
grep "gz-transport1" CMakeLists.txt   # should show both 12 and 13
```
