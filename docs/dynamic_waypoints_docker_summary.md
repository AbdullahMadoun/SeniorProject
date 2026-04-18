# Dynamic Waypoints Docker Summary

## What I Changed

I changed the dynamic-waypoint simulation path so it no longer depends on a hidden local PX4 checkout.

The main fixes:

- Added a shared simulation runtime helper in `autonomy/drone_system/simulation_runtime.py`.
- Refactored `autonomy/scripts/run_live_interactive_mission.py` so it can run in:
  - Windows + WSL mode
  - native Linux / Docker mode
- Made `deploy/simulation/bootstrap_remote.sh` self-provision PX4:
  - clones `vendor/PX4-Autopilot` automatically if missing
  - pins PX4 to `v1.14.3`
  - prepares the autonomy virtual environment
  - builds `px4_sitl gz_x500`
- Added a Docker-first simulation stack:
  - `deploy/simulation/Dockerfile`
  - `deploy/simulation/docker_entrypoint.sh`
  - `docker-compose.simulation.yml`
- Updated `deploy/simulation/README.md` so the Docker path is the default fresh-machine flow.
- Relaxed `.dockerignore` so the simulation image can actually include the autonomy code and planner/dashboard artifacts.

## What This Solves

Before this change, a fresh machine could fail because recent commits assumed `vendor/PX4-Autopilot` already existed outside the GitHub clone.

Now the intended path is:

1. clone the repo
2. build the simulation container
3. open the planner
4. run the mission

No manual PX4 checkout should be required on the host.

## How To Try It

From the repo root:

```powershell
docker compose -f .\docker-compose.simulation.yml up --build
```

Then open:

```text
http://127.0.0.1:8625/planner/index.html
```

Recommended flow:

1. Start the compose stack.
2. Wait for the container to finish first-time bootstrap/build.
3. Open the planner page.
4. Create or load a mission.
5. Launch the simulation from the existing planner / mission API flow.

Artifacts and logs will still go under `artifacts/`, including:

- `artifacts/sitl_logs/`
- `artifacts/live_px4/`
- `artifacts/replay_bundle/latest/`
- `artifacts/showcase/latest/`
- `artifacts/dashboard/`

## If You Want To Try It On Vast

Use a Vast VM path, not a standard container path, if you want the remote host itself to run Docker/Compose.

High-level steps:

1. create or use a Vast VM
2. clone this repo on the VM
3. run the same Docker Compose command there
4. expose or tunnel port `8625`
5. open `/planner/index.html`

## What I Verified

I verified the Python-side changes with targeted unit tests:

```powershell
python -m unittest autonomy.tests.test_simulation_runtime autonomy.tests.test_execute_interactive_mission autonomy.tests.test_mission_api.MissionApiTests.test_runner_command_includes_execution_cpu_cores autonomy.tests.test_mission_api.MissionApiTests.test_root_redirects_to_dashboard
```

## What I Did Not Verify Here

I did not run:

- a full Docker image build
- a live SITL mission inside Docker
- a real Vast end-to-end run

So the remaining step is real runtime validation:

```powershell
docker compose -f .\docker-compose.simulation.yml up --build
```

If that succeeds, your friend should be able to test dynamic waypoints from a clean machine without manually fixing PX4 on the host.
