"""Rate limiting middleware for production."""
from fastapi import Request, HTTPException
from datetime import datetime, timedelta
from collections import defaultdict
import time

# Simple in-memory rate limiter (for demo - use Redis in production)
request_counts = defaultdict(list)
RATE_LIMIT = 60  # requests per minute
WINDOW = 60  # seconds

async def rate_limit_middleware(request: Request, call_next):
    """Limit requests to 60 per minute per IP."""
    client_ip = request.client.host
    now = time.time()
    
    # Clean old requests
    request_counts[client_ip] = [
        req_time for req_time in request_counts[client_ip]
        if now - req_time < WINDOW
    ]
    
    # Check rate limit
    if len(request_counts[client_ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )
    
    # Record request
    request_counts[client_ip].append(now)
    
    response = await call_next(request)
    return response
