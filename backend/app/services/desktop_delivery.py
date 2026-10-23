"""Deliver already generated Studio bytes through the bound desktop transport."""


async def deliver_studio_files(files):
    from app.services.desktop_context import desktop_executor, desktop_mode
    if desktop_mode.get() != 'director' or desktop_executor.get() is None:
        return False
    from turn_scope import deliver_now
    ready = [item for item in files if item.get('bytes')]
    return await deliver_now('', ready) if ready else False
