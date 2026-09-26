# Math Duel

A small, dependency-free, two-player math challenge. Both players use their own devices. The Python server owns room state, validates answers, switches turns, and enforces the 100-second deadline.

## Rules implemented

- Two players join a five-character room code or invite link.
- Players choose Rock, Paper, or Scissors simultaneously. A tie repeats. The winner takes rounds 1 and 3.
- Each round's active player chooses a whole starting number from −999 to 999. The game adds three random numbers from 1 to 10, then chooses a target reachable using all four numbers exactly once with `+`, `−`, `×`, `÷`, and parentheses.
- Division must produce a whole number. The active player has 100 seconds. A correct expression earns one point; a wrong answer or timeout gives no point.
- The other player takes round 2. After exactly three rounds, the higher score wins and equal scores are a draw.

## Run locally

Requires Python 3.11 or later. In this folder run:

```powershell
python server.py
```

Open http://localhost:8000 on this device. For another device on the same Wi-Fi, use this computer's local network address and port 8000. For play across the internet, deploy the service.

## Publish a free live URL with Render

Render's free web service supports WebSockets. Its free service may spin down after 15 minutes without traffic, so the first connection after inactivity can take a short while. Rooms live in server memory: an app restart or free-service spin-down ends any in-progress room.

1. Create a free account at [GitHub](https://github.com/signup) and a free account at [Render](https://dashboard.render.com/register). Both services require accounts to publish a persistent public URL.
2. Create a **public** GitHub repository named `math-duel`.
3. Add the contents of this `math-duel` folder to the repository. On GitHub, use **Add file → Upload files**, drag in `server.py`, `index.html`, and `render.yaml`, then commit the files.
4. In Render, choose **New + → Blueprint** and connect GitHub. Select the `math-duel` repository and deploy the blueprint. The included `render.yaml` configures the free Python WebSocket service.
5. When Render finishes, open the `onrender.com` URL shown on the service page. Create a room and send the invite link to the second player.

The first player to create the room is the host and starts the RPS phase. Both players still make their choices independently on their own devices.

## Implementation notes

- Uses only Python standard-library modules; no package installation or API keys.
- `/` serves the game, any `/{room-code}` path serves the game for invite links, and `/ws` handles the live WebSocket connection.
- Room state is intentionally in memory for this lightweight free deployment. It is suitable for casual sessions, not durable or multi-instance hosting.
