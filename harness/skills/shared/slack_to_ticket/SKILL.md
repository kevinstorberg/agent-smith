---
name: slack-to-ticket
description: Use when asked to create a Jira ticket from a Slack message or thread. Reads the Slack thread, extracts key information, confirms details with the user, and creates a properly formatted Jira ticket. Requires Slack MCP and Atlassian MCP.
---

# Slack → Jira Ticket

Turn a Slack message or thread into a Jira ticket.

---

## Dependencies

This skill requires two MCP integrations to be enabled:

| MCP | Why it's needed |
|-----|----------------|
| **Slack MCP** (`slack@claude-plugins-official`) | Read the message/thread content |
| **Atlassian MCP** (`atlassian@claude-plugins-official`) | Create the Jira ticket |

If either is missing, tell the user which one is needed and stop.

---

## Step 1: Get the Slack Content

If the user provided a Slack message URL, parse it:

```
https://sondermind.slack.com/archives/<CHANNEL_ID>/p<TS_NO_DECIMAL>
```

- `CHANNEL_ID` = e.g. `C09MUB2UDSQ`
- `MESSAGE_TS` = insert decimal 6 chars from end of the `p...` value
  - e.g. `p1771912913499829` → `1771912913.499829`

Read the thread using `mcp__plugin_slack_slack__slack_read_thread` (channel_id + message_ts).

If the user provided a message URL (not a thread), use `mcp__plugin_slack_slack__slack_read_channel` with the timestamp to get the message and any replies.

If the user pasted the message content directly (no URL), skip to Step 2.

---

## Step 2: Analyze and Summarize

From the thread content, extract:

- **What happened / what's being asked** — the core problem or request
- **Who reported it** — author of the original message
- **Any relevant context** — error messages, links, steps to reproduce, affected users
- **Ticket type guess** — Bug if something is broken, Task if it's a one-off action, Story/Feature if it's a new capability

Summarize the thread into a proposed ticket. Do not ask the user anything yet — form your own opinion first.

---

## Step 3: Confirm Details with User

Present your proposed ticket and ask for confirmation/corrections in a single message:

```
Here's what I'll create:

**Type:** Bug / Task / Story
**Project:** SM (or ask if unknown)
**Summary:** <one-line summary>
**Description:**
<formatted description>

Does this look right? Or let me know:
- Different ticket type?
- Different project?
- Assignee to add?
- Priority?
```

Wait for the user to confirm or provide corrections.

### Jira Project Defaults

If the Slack channel maps to a known team, default to that project:

| Slack Channel | Jira Project |
|--------------|-------------|
| `C09MUB2UDSQ` (CAI team) | `CAI` |

If unknown, ask: `"Which Jira project? (e.g. SM, CAI, PLT)"`

---

## Step 4: Format the Description

Format the ticket description using the `/write_ticket` skill structure.

In the **Context** section, include the Slack thread URL so the ticket links back to
the original conversation.

---

## Step 5: Create the Jira Ticket

Use `mcp__plugin_atlassian_atlassian__createJiraIssue`:

```
cloudId: "sondermind-jira.atlassian.net"
projectKey: <PROJECT>
issueTypeName: <Bug | Task | Story>
summary: <SUMMARY>
description: <FORMATTED_DESCRIPTION>
assignee_account_id: <if provided>
```

---

## Step 6: Confirm and Share

After creation, reply with:

```
✅ Ticket created!

🎫 <TICKET_KEY> — <SUMMARY>
🔗 https://sondermind-jira.atlassian.net/browse/<TICKET_KEY>
```

If the user wants to post the ticket link back to the Slack thread, ask:
`"Want me to reply in the Slack thread with the ticket link?"`

If yes, use `mcp__plugin_slack_slack__slack_send_message` with `thread_ts` set to the original message TS.
