"""Dependency-free WebSocket game server for Math Duel."""
import asyncio, base64, hashlib, json, os, random, re, struct, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
ROOMS = {}
PORT = int(os.environ.get("PORT", "8000"))

def clean_name(s):
    return re.sub(r"[^\w -]", "", str(s or "Player")).strip()[:18] or "Player"

def apply(a, op, b):
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if op == "/" and b and a % b == 0: return a // b
    return None

def make_puzzle(start):
    nums = [start] + [random.randint(1, 10) for _ in range(3)]
    states = {(tuple(sorted((x,))), x) for x in nums}
    # Dynamic programming over subsets; retain all integer values reachable.
    vals = {1 << i: {n} for i, n in enumerate(nums)}
    for size in range(2, 5):
        for mask in range(1, 16):
            if mask.bit_count() != size: continue
            out = set()
            sub = (mask - 1) & mask
            while sub:
                other = mask ^ sub
                if other and sub < other:
                    for a in vals.get(sub, ()):
                        for b in vals.get(other, ()):
                            for op in "+-* /".replace(" ", ""):
                                x = apply(a, op, b)
                                if x is not None and -9999 <= x <= 9999: out.add(x)
                                if op in "- /".replace(" ", ""):
                                    x = apply(b, op, a)
                                    if x is not None and -9999 <= x <= 9999: out.add(x)
                sub = (sub - 1) & mask
            vals[mask] = out
    targets = [n for n in vals[15] if 10 <= n <= 200]
    target = random.choice(targets) if targets else 24
    return nums, target

def eval_expr(expr, numbers):
    # Safe grammar: literals, four arithmetic operations and parentheses.
    expr = expr.replace("×", "*").replace("÷", "/").replace("−", "-")
    if len(expr) > 120 or not re.fullmatch(r"[\d+*/(). \-]+", expr): return None
    tokens = re.findall(r"\d+|[()+*/-]", expr.replace(" ", ""))
    if "".join(tokens) != expr.replace(" ", ""): return None
    pos = 0
    def atom():
        nonlocal pos
        if pos >= len(tokens): raise ValueError()
        if tokens[pos] == "(":
            pos += 1; v = add()
            if pos >= len(tokens) or tokens[pos] != ")": raise ValueError()
            pos += 1; return v
        if tokens[pos] == "-": pos += 1; return -atom()
        t = tokens[pos]
        if not t.isdigit(): raise ValueError()
        pos += 1; return int(t)
    def mul():
        nonlocal pos
        v = atom()
        while pos < len(tokens) and tokens[pos] in "*/":
            op = tokens[pos]; pos += 1; b = atom()
            if op == "/":
                if b == 0: raise ValueError()
                if v % b != 0: raise ValueError()
                v //= b
            else: v *= b
        return v
    def add():
        nonlocal pos
        v = mul()
        while pos < len(tokens) and tokens[pos] in "+-":
            op = tokens[pos]; pos += 1; b = mul()
            v = v + b if op == "+" else v - b
        return v
    try:
        value = add()
        used = [int(t) for t in tokens if t.isdigit()]
        if pos != len(tokens) or sorted(used) != sorted(numbers): return None
        return value
    except (ValueError, ZeroDivisionError, OverflowError): return None

def public(room):
    return {k: v for k, v in room.items() if k not in ("choices", "hands", "sockets")}

def packet(code, data):
    raw = json.dumps(data).encode(); n = len(raw)
    head = bytes([0x81, n]) if n < 126 else bytes([0x81,126])+struct.pack("!H",n) if n < 65536 else bytes([0x81,127])+struct.pack("!Q",n)
    return head + raw

async def send(ws, data):
    ws.write(packet("", data)); await ws.drain()

async def read_frame(reader):
    h = await reader.readexactly(2); n = h[1] & 127
    if n == 126: n = struct.unpack("!H", await reader.readexactly(2))[0]
    elif n == 127: n = struct.unpack("!Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if h[1] & 128 else None
    data = await reader.readexactly(n)
    if mask: data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return h[0] & 15, data

async def broadcast(room):
    dead=[]
    for ws in list(room.get("sockets", {}).values()):
        try: ws.write(packet("", {"type":"state", "room":public(room)})); await ws.drain()
        except Exception: dead.append(ws)
    for ws in dead:
        for pid, s in list(room.get("sockets", {}).items()):
            if s is ws: room["sockets"].pop(pid,None)

def begin_round(room, start):
    nums, target = make_puzzle(start)
    room.update(phase="math", numbers=nums, target=target, deadline=time.time()+100, roundStart=start, lastResult=None)

async def handle(reader, writer):
    try:
        req = (await reader.readuntil(b"\r\n\r\n")).decode("latin1")
        line=req.splitlines()[0]; path=urlparse(line.split()[1]); query=parse_qs(path.query)
        if path.path != "/ws":
            f = ROOT / (path.path.rsplit("/",1)[-1] if path.path.startswith("/static/") else "index.html")
            body=f.read_bytes(); typ="text/html; charset=utf-8" if f.suffix==".html" else "text/plain"
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: {typ}\r\nContent-Length: {len(body)}\r\nCache-Control: no-cache\r\n\r\n".encode()+body); await writer.drain(); return
        headers={x.split(":",1)[0].lower():x.split(":",1)[1].strip() for x in req.splitlines()[1:] if ":" in x}
        key=headers.get("sec-websocket-key")
        if path.path != "/ws" or not key:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"); await writer.drain(); return
        accept=base64.b64encode(hashlib.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        writer.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode()); await writer.drain()
        ws=writer; player=None; room=None
        while True:
            op, raw = await read_frame(reader)
            if op == 8: break
            if op == 9: writer.write(bytes([0x8A,len(raw)])+raw); await writer.drain(); continue
            msg=json.loads(raw); action=msg.get("action")
            if action == "join":
                code=(msg.get("code") or "").upper()[:6]; name=clean_name(msg.get("name")); pid=msg.get("id") or str(random.randrange(10**12))
                if msg.get("create"):
                    code="".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789",k=5))
                    while code in ROOMS: code="".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789",k=5))
                    ROOMS[code]={"code":code,"phase":"lobby","players":[],"round":0,"score":{},"sockets":{},"choices":{},"hands":{}}
                room=ROOMS.get(code)
                if not room: await send(ws,{"type":"error","message":"Room not found. Check the code."}); continue
                existing=next((p for p in room["players"] if p["id"]==pid),None)
                if existing: existing["name"]=name; player=existing
                elif room["phase"] != "lobby" or len(room["players"])>=2:
                    await send(ws,{"type":"error","message":"This room already has two players."}); continue
                else:
                    player={"id":pid,"name":name}; room["players"].append(player); room["score"][pid]=0
                room["sockets"][pid]=ws
                await send(ws,{"type":"joined","id":pid,"code":code}); await broadcast(room)
            elif room and player:
                pid=player["id"]
                if action == "rps" and room["phase"]=="rps":
                    room["rpsResult"] = None
                    if msg.get("choice") in ("rock","paper","scissors"): room["choices"][pid]=msg["choice"]
                    if len(room["choices"])==2:
                        a,b=room["players"]; x,y=room["choices"].get(a["id"]),room["choices"].get(b["id"])
                        if x==y: room["rpsResult"]="tie"; room["choices"]={}
                        else:
                            win=(x,y) in (("rock","scissors"),("paper","rock"),("scissors","paper")); first=a if win else b
                            room["first"]=first["id"]; room["rpsResult"]=first["name"]+" wins!"; room["phase"]="ready"
                    await broadcast(room)
                elif action == "start" and room["phase"]=="lobby" and len(room["players"])==2 and room["players"][0]["id"]==pid:
                    room.update(phase="rps",rpsResult=None,choices={}); await broadcast(room)
                elif action == "retry_rps" and room["phase"]=="rps": room["choices"]={}; room["rpsResult"]=None; await broadcast(room)
                elif action == "begin" and room["phase"]=="ready" and room["first"]==pid:
                    room["round"]=1; room["current"]=room["first"]; room["phase"]="pick"; await broadcast(room)
                elif action == "choose_number" and room["phase"]=="pick" and room.get("current")==pid:
                    try: start=max(-999, min(999, int(msg.get("number"))))
                    except (ValueError, TypeError): start=None
                    if start is not None: begin_round(room,start); await broadcast(room)
                elif action == "submit" and room["phase"]=="math" and room.get("current")==pid:
                    if time.time() <= room["deadline"]:
                        value=eval_expr(str(msg.get("expression","")),room["numbers"])
                        hit=value is not None and abs(value-room["target"])<1e-9
                        if hit: room["score"][pid]=room["score"].get(pid,0)+1
                        room["lastResult"]={"id":pid,"name":player["name"],"hit":hit,"expression":str(msg.get("expression",""))[:120]}
                        room["phase"]="result"; room["deadline"]=None; await broadcast(room)
                elif action == "next" and room["phase"]=="result" and room["round"]<3:
                    room["round"]+=1
                    players=room["players"]
                    room["current"]=players[0 if players[0]["id"]!=room["first"] else 1]["id"] if room["round"]==2 else room["first"]
                    room["phase"]="pick"; room["deadline"]=None; await broadcast(room)
                elif action == "finish" and room["phase"]=="result" and room["round"]==3:
                    room["phase"]="finished"; await broadcast(room)
    except (asyncio.IncompleteReadError, ConnectionError, json.JSONDecodeError, KeyError): pass
    finally:
        if 'room' in locals() and room and 'player' in locals() and player:
            room.get("sockets",{}).pop(player["id"],None); await broadcast(room)
        writer.close()

async def ticker():
    while True:
        await asyncio.sleep(0.5)
        for room in list(ROOMS.values()):
            if room.get("phase")=="math" and time.time()>=room.get("deadline",0):
                active=next(p for p in room["players"] if p["id"]==room["current"])
                room["lastResult"]={"id":active["id"],"name":active["name"],"hit":False,"timeout":True,"expression":""}
                room["phase"]="result"; room["deadline"]=None; await broadcast(room)

async def main():
    server=await asyncio.start_server(handle,"0.0.0.0",PORT)
    asyncio.create_task(ticker())
    async with server: await server.serve_forever()

if __name__=="__main__": asyncio.run(main())
