import asyncio
from typing import Dict

# In-flight generation tasks per account id — cancel on a new request.
USER_TASKS: Dict[int, asyncio.Task] = {}
