# FastAPI WebSocket Chat with GridFS Uploads

A simple FastAPI chat application that supports:
- user signup/login
- WebSocket chat with broadcast and private messages
- file and image upload using MongoDB GridFS
- file download and inline image preview

## Requirements

- Python 3.11+ (Python 3.13 tested)
- MongoDB running locally on `mongodb://localhost:27017/`
- Python packages:
  - fastapi
  - uvicorn
  - pymongo
  - gridfs
  - argon2-cffi
  - python-multipart

## Setup

1. Install dependencies:

```bash
python -m pip install fastapi uvicorn pymongo argon2-cffi python-multipart
```

2. Start MongoDB locally.
3. Run the app:

```bash
python main.py
```

4. Open the browser at `http://127.0.0.1:8000`

## Usage

- Sign up and log in
- Use the chat window to send broadcast or private text messages
- Upload files or images using the file input
- Images display inline in chat; other files are provided as download links

## Notes

- Uploaded files are stored in MongoDB GridFS.
- Files are served from `/files/{file_id}`.
- The app uses session middleware for authentication.
