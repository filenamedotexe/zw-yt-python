from flask import Flask
from app import app as application

app = application

# Vercel serverless function handler
def handler(request, context):
    return app(request, context)