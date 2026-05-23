from click import password_option
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect, Form, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from httpx import request
from argon2 import PasswordHasher, exceptions
from argon2.exceptions import VerifyMismatchError
from pymongo import MongoClient
from bson import ObjectId
from starlette.middleware.sessions import SessionMiddleware
import gridfs
import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)


client= MongoClient("mongodb://localhost:27017/")
  
db= client["database1"]
collection1= db["collection1"]

ph= PasswordHasher()

app= FastAPI()

templates= Jinja2Templates(directory="templates")

app.add_middleware(SessionMiddleware, secret_key="super-secret-key")

fs= gridfs.GridFS(db)



import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections.setdefault(username, []).append(websocket)
        await self.old_messages(websocket, username)
        await self.broadcast_user_list()

    async def disconnect(self, websocket: WebSocket, username: str):
        if username in self.active_connections:
            self.active_connections[username].remove(websocket)
            if not self.active_connections[username]:
                del self.active_connections[username]

    async def send_personal_message(self, message: str, username: str):
        if username in self.active_connections:
            for ws in self.active_connections[username]:
                await ws.send_text(message)

    async def broadcast(self, message: str):
        for sockets in self.active_connections.values():
            for ws in sockets:
                await ws.send_text(message)

    async def broadcast_user_list(self):
        users = list(self.active_connections.keys())
        payload = {"type": "user_list", "users": users}
        message = "__USER_LIST__:" + json.dumps(payload)
        for sockets in self.active_connections.values():
            for ws in sockets:
                await ws.send_text(message)

    async def old_messages(self, websocket: WebSocket, username: str):
        cursor = collection1.find({"$or": [{"from": username}, {"to": username}, {"to": "all"}]})
        for msg in cursor:
            if msg.get("type") == "file":
                payload = {
                    "type": "file",
                    "from": msg["from"],
                    "to": msg["to"],
                    "filename": msg["filename"],
                    "content_type": msg.get("content_type", "application/octet-stream"),
                    "file_id": str(msg["file_id"]),
                    "history": True
                }
                await websocket.send_text("__FILE__:" + json.dumps(payload))
            elif msg["to"] == "all":
                payload = {"type": "history", "subtype": "broadcast", "from": msg["from"], "message": msg["message"]}
                await websocket.send_text("__HISTORY__:" + json.dumps(payload))
            elif msg["to"] == username:
                payload = {"type": "history", "subtype": "private", "from": msg["from"], "message": msg["message"]}
                await websocket.send_text("__HISTORY__:" + json.dumps(payload))


manager = ConnectionManager()

@app.get("/")
async def profile(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    username = websocket.scope.get("session", {}).get("username")
    if not username:
        await websocket.accept()
        await websocket.send_text("Unauthorized: please log in.")
        await websocket.close()
        return

    await manager.connect(websocket, username)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                msg_type = payload.get("type", "broadcast")
                content = payload.get("message", "")
                to_user = payload.get("to")
            except json.JSONDecodeError:
                msg_type = "broadcast"
                content = data
                to_user = None

            if msg_type == "private" and to_user:
                await manager.send_personal_message(f"PM from {username}: {content}", to_user)
                await manager.send_personal_message(f"You (to {to_user}): {content}", username)
                collection1.insert_one({"from": username, "to": to_user, "message": content})
            else:
                await manager.broadcast(f"Broadcast from {username}: {content}")
                collection1.insert_one({"from": username, "to": "all", "message": content})
    except WebSocketDisconnect:
        await manager.disconnect(websocket, username)
        await manager.broadcast(f"client #{username} left the chat")
        await manager.broadcast_user_list()



@app.post("/login")
async def login(request: Request,
                username: str = Form(...),
                password: str= Form(...)):
    try:
        if username == collection1.find_one({"username": username})["username"]:
            if ph.verify(collection1.find_one({"username": username})["password"], password):
                request.session["username"]= username
                return templates.TemplateResponse("index.html", {"request": request, "message": "Login successful"})
            
            else:
                return templates.TemplateResponse("login.html", {"request": request, "message": "Incorrect password"})

    except TypeError:
        return templates.TemplateResponse("login.html", {"request": request, "message": "User not found"})

@app.get("/signup")
async def signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/upload")
async def upload(request: Request,
                 file: UploadFile = File(...),
                 to: str | None = Form(None),
                 private: bool = Form(False)):
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    target = to if private and to else "all"
    file_data = await file.read()
    grid_id = fs.put(
        file_data,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        metadata={"from": username, "to": target}
    )
    message_doc = {
        "type": "file",
        "from": username,
        "to": target,
        "filename": file.filename,
        "content_type": file.content_type or "application/octet-stream",
        "file_id": grid_id
    }
    collection1.insert_one(message_doc)

    payload = {
        "type": "file",
        "from": username,
        "to": target,
        "filename": file.filename,
        "content_type": message_doc["content_type"],
        "file_id": str(grid_id)
    }
    if target == "all":
        await manager.broadcast("__FILE__:" + json.dumps(payload))
    else:
        await manager.send_personal_message("__FILE__:" + json.dumps(payload), target)
        await manager.send_personal_message("__FILE__:" + json.dumps(payload), username)

    return {"status": "ok", "file_id": str(grid_id)}

@app.get("/files/{file_id}")
async def get_file(file_id: str):
    try:
        obj_id = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    try:
        grid_out = fs.get(obj_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    disposition = "inline" if (grid_out.content_type or "").startswith("image/") else "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{grid_out.filename}"'}
    return StreamingResponse(grid_out, media_type=grid_out.content_type, headers=headers)

@app.post("/signup")
async def signup(request: Request,
                 username: str = Form(...),
                 password: str = Form(...)
                 ):
    try: 
        if username == collection1.find_one({"username": username})["username"]:
            return templates.TemplateResponse("signup.html", {"request": request, "message": "Username already exists"})
    except TypeError:
        hashed_password= ph.hash(password)
        collection1.insert_one({"username": username, "password": hashed_password})
        return templates.TemplateResponse("login.html", {"request": request, "message": "Signup successful"})
    
