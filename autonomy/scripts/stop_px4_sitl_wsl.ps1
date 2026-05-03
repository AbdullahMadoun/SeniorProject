$command = @(
    "bash",
    "-lc",
    "pkill -f '/px4( |$)|gz sim|make px4_sitl' || true"
)

wsl @command
