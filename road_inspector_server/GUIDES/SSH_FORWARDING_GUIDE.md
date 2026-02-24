# Accessing the Vast.ai API from your Local Laptop

Since your FastAPI server is running on a remote Vast.ai instance, you have two main options to access it from your personal laptop:

## Option 1: SSH Local Port Forwarding (Recommended & Most Secure)

You don't need `ngrok`! Because you already have an SSH connection to the Vast.ai instance (as shown by your SSH config), you can simply "forward" the remote API port (`17612`) directly to your local laptop.

This creates a secure tunnel, making your laptop think the API is running locally on `localhost:17612`.

### Step 1: Update your SSH Config on your Local Laptop
Open your local `ssh_config` file (usually at `C:\Users\mohdm\.ssh\config`) and modify the `LocalForward` line for your Vast.ai host.

Change it from this:
```
LocalForward 8080 localhost:8080
```
To this (forwarding the API port):
```
LocalForward 17612 localhost:17612
```

### Step 2: Connect over SSH
On your local laptop, open your terminal/PowerShell and connect to the Vast.ai instance using your SSH config alias:
```bash
ssh vastai
```

As long as this SSH terminal window remains open, the tunnel is active!

### Step 3: Run Inference from your Laptop
Now, on your personal laptop, you can point your Python scripts or `curl` commands directly to `localhost:17612`. The SSH tunnel will securely forward the request to the Vast.ai GPU server!

```python
import requests
import base64

# Run this script on your WEAK PERONAL LAPTOP!
with open("local_pothole_image.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

# Point to localhost:17612 (the SSH tunnel handles the rest)
resp = requests.post(
    "http://localhost:17612/analyze",
    headers={"X-API-Key": "road-inspector-secret-key-2024"},
    json={"image_b64": img_b64, "location": {"lat": 0.0, "lon": 0.0}}
)

print(resp.json())
```

---

## Option 2: Direct TCP Connection (If you prefer not to use SSH tunnels)

Vast.ai instances are behind a NAT router. If you want to access the API directly over the internet *without* an SSH tunnel, you need to expose a port in the Vast.ai dashboard.

1. Go to your Vast.ai dashboard (Instances page).
2. Find your running instance (185.62.108.226).
3. Look for the "Port Forwarding" or "Network" settings for that instance.
4. You need to map a **Public Port** (e.g., `45000`) to the **Internal Port** (`17612`).
5. Once mapped, you would send your API requests from your laptop to `http://185.62.108.226:45000/analyze`.

*Note: Option 1 (SSH Tunneling) is generally safer because your API traffic is encrypted through the SSH connection.*
