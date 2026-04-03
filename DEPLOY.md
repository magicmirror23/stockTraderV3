# Deployment instructions
# StockTrader â€“ Deployment Guide

## Option 1: Render.com (Recommended â€” Free, Always Online)

### Step 1: Push code to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/stocktrader.git
git push -u origin main
```

### Step 2: Deploy on Render.com
1. Go to [https://render.com](https://render.com) and sign up (free)
2. Click **"New" â†’ "Blueprint"**
3. Connect your GitHub repo
4. Render reads `render.yaml` and auto-creates:
   - Web service (your app)
   - PostgreSQL database (free)
5. Click **"Apply"** â€” your app deploys automatically
6. You get a public URL like: `https://stocktrader-xxxx.onrender.com`

### Step 3: Access from any device
- Open the Render URL on your phone, tablet, or any computer
- The URL is publicly accessible 24/7

---

## Option 2: Railway.app (Simple, $5 free credit)

1. Go to [https://railway.app](https://railway.app)
2. Click **"New Project" â†’ "Deploy from GitHub repo"**
3. Connect your repo
4. Railway auto-detects the Dockerfile
5. Add PostgreSQL plugin from the dashboard
6. Set environment variables from `.env.example`
7. Deploy â€” get a public URL

---

## Option 3: Run on your PC + ngrok (Quick, free)

### Make it accessible from other devices on your network:
```bash
# Start backend
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# Start frontend
cd frontend && ng serve --host 0.0.0.0

# Access from other devices using your PC's IP:
# http://YOUR_PC_IP:4200
```

### Make it accessible from anywhere (internet):
```bash
# Install ngrok
# Download from https://ngrok.com/download

# Start your backend
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# In another terminal, expose it:
ngrok http 8000

# You get a public URL like: https://abc123.ngrok-free.app
```

---

## Option 4: Docker deploy on any VPS

```bash
# Build the production image
docker build -t stocktrader .

# Run it
docker run -d -p 8000:8000 --env-file .env --name stocktrader stocktrader

# Your app is at http://YOUR_SERVER_IP:8000
```

---

## Notes
- The Dockerfile builds Angular frontend and serves it from FastAPI (single container)
- All API routes work at `/api/v1/*`
- Frontend is served at the root `/`
- API docs available at `/docs`
