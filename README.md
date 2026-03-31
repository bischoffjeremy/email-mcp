<p align="center">
  <img src="logo.png" alt="Email MCP" width="800">
</p>

# Email MCP Server

MCP server for email via IMAP (read) and SMTP (send). Built with [FastMCP](https://gofastmcp.com/).

Works with any standard email provider: **Gmail**, **Outlook**, **Infomaniak**, **ProtonMail Bridge**, **self-hosted**, etc.

## Tools

### Read (IMAP)

| Tool | Description |
|------|-------------|
| `list_mailboxes` | List all mailbox folders (Inbox, Sent, Drafts, …) |
| `get_inbox` | Get most recent emails from inbox |
| `get_unread` | Get unread emails |
| `get_unread_count` | Count of unread emails |
| `read_email` | Read a specific email (full body + attachments) |
| `search_emails` | Search by keyword in subject, sender, or body |
| `get_emails_from` | Get emails from any folder (Sent, Drafts, Trash, …) |
| `mark_as_read` | Mark an email as read |
| `mark_as_unread` | Mark an email as unread |

### Write (SMTP)

| Tool | Description |
|------|-------------|
| `send_email`\* | Send an email (to, cc, bcc) |
| `reply_to_email`\* | Reply to an email by UID |

### Danger Zone

| Tool | Description |
|------|-------------|
| `delete_email`\*\* | Delete an email |

\* Disabled by default. Set `ALLOW_SEND=true` to enable.
\*\* Disabled by default. Set `ALLOW_DELETE=true` to enable.

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env with your email credentials

docker compose up -d --build
```

The server runs on `http://localhost:8002/mcp/` (Streamable HTTP transport).

### Local

```bash
pip install .
export IMAP_HOST="imap.gmail.com"
export SMTP_HOST="smtp.gmail.com"
export EMAIL_USER="you@gmail.com"
export EMAIL_PASSWORD="your-app-password"
fastmcp run src/server.py:mcp --transport streamable-http --host 0.0.0.0 --port 8002
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `IMAP_HOST` | IMAP server hostname | *required* |
| `IMAP_PORT` | IMAP port | `993` |
| `SMTP_HOST` | SMTP server hostname | *required* |
| `SMTP_PORT` | SMTP port | `587` |
| `EMAIL_USER` | Email username / address | *required* |
| `EMAIL_PASSWORD` | Email password / app password | *required* |
| `EMAIL_FROM` | From address for sent emails | `EMAIL_USER` |
| `MAX_RESULTS` | Max emails per query | `25` |
| `ALLOW_SEND` | Enable send tools (`true`/`false`) | `false` |
| `ALLOW_DELETE` | Enable delete tool (`true`/`false`) | `false` |

### Common Provider Settings

| Provider | IMAP Host | SMTP Host |
|----------|-----------|-----------|
| Gmail | `imap.gmail.com` | `smtp.gmail.com` |
| Outlook / Microsoft 365 | `outlook.office365.com` | `smtp.office365.com` |
| Infomaniak | `mail.infomaniak.com` | `mail.infomaniak.com` |
| ProtonMail (Bridge) | `127.0.0.1:1143` | `127.0.0.1:1025` |
| Yahoo | `imap.mail.yahoo.com` | `smtp.mail.yahoo.com` |

> **Tip:** For Gmail, create an [App Password](https://myaccount.google.com/apppasswords) and use it as `EMAIL_PASSWORD`.

## MCP Client Configuration

Add to your MCP client config (e.g. Claude Desktop, VS Code):

```json
{
  "mcpServers": {
    "email": {
      "url": "http://localhost:8002/mcp/"
    }
  }
}
```
