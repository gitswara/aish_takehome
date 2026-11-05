"""Minimal Gmail MCP server exposing a send_email tool (SMTP + App Password).

Place at: mcp_server/gmail_server.py
Reads GMAIL_USER and GMAIL_APP_PASSWORD from the project's .env file.
"""
import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

mcp = FastMCP("gmail")


@mcp.tool()
def send_email(to: str, subject: str, body: str, references: str = "") -> str:
    """Send a plain-text email from the configured Gmail account.

    Args:
        to: Recipient email address.
        subject: Subject line.
        body: Plain-text body.
        references: Optional Message-ID this email refers to (sets References and In-Reply-To).
    """
    user = os.environ["GMAIL_USER"]
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain="dedup.local")
    if references:
        msg["References"] = references
        msg["In-Reply-To"] = references
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, os.environ["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)
    return f"sent to {to} (Message-ID {msg['Message-ID']})"


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
