# Agent API: Create Task from Thread

## Summary
Agents now have access to the `POST /api/v1/threads/{thread_id}/create-task` endpoint.

## Endpoint Details

**POST** `/api/v1/threads/{thread_id}/create-task`

### Authentication
- **Supports both**: User authentication (Bearer token) AND Agent authentication (X-Agent-Token header)
- Previously: User-only endpoint
- Now: Uses `ACTOR_DEP` dependency allowing both users and agents

### Request
```http
POST /api/v1/threads/{thread_id}/create-task
X-Agent-Token: your-agent-token
```

No request body required.

### Response
Returns the updated thread with the newly created task linked:
```json
{
  "id": "thread-uuid",
  "channel_id": "channel-uuid",
  "topic": "Bug: login page not loading",
  "task_id": "newly-created-task-uuid",
  "is_resolved": false,
  "is_pinned": false,
  "message_count": 2,
  "created_at": "2026-03-26T10:00:00Z",
  "updated_at": "2026-03-26T10:30:00Z"
}
```

### Behavior
1. Creates a new task on the board using the thread's topic as the task title
2. Sets initial task status to "inbox" and priority to "medium"
3. Links thread and task bidirectionally:
   - `thread.task_id = task.id`
   - `task.thread_id = thread.id`
4. Marks the thread as active (unresolved)
5. Adds a system notification message to the thread: "Task created from this conversation: #{task.id}"
6. When an agent creates the task, `created_by_user_id` is `None`
7. When a user creates the task, `created_by_user_id` is set to the user's ID

### Error Cases

#### 409 Conflict
Thread already has a linked task:
```json
{
  "detail": "Thread already has a linked task."
}
```

#### 404 Not Found
- Thread doesn't exist
- Channel doesn't exist
- Board doesn't exist

#### 401 Unauthorized
Missing or invalid authentication credentials

## Example Usage

### Agent Creating Task from Thread
```python
import httpx

async def create_task_from_support_thread(thread_id: str, agent_token: str):
    """Agent creates a task from a support thread."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"http://localhost:8000/api/v1/threads/{thread_id}/create-task",
            headers={"X-Agent-Token": agent_token}
        )
        response.raise_for_status()
        thread = response.json()
        print(f"Created task {thread['task_id']} from thread {thread['id']}")
        return thread
```

### Use Case
When an agent detects a support thread that requires action:
1. Agent identifies the thread needs to become a tracked task
2. Agent calls this endpoint to convert the conversation to a task
3. Task appears on the board with the thread topic as the title
4. Thread and task are now linked - comments on the task appear in the thread
5. Completing the task auto-resolves the thread

## Testing
Added comprehensive tests in `backend/tests/channels/test_agent_create_task_from_thread.py`:
- ✅ Agent can create task from thread
- ✅ Agent cannot create duplicate task (409 conflict)
- ✅ Agent-created tasks have `created_by_user_id` as None

All tests passing.
