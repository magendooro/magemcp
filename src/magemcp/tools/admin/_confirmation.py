import os
import hashlib
import time
from typing import Any

def needs_confirmation(action: str, entity_id: str, confirm: bool = False) -> dict[str, Any] | None:
    """Return confirmation prompt if confirm=False, None if confirmed.
    
    The token is a time-based hash that changes every 5 minutes (300 seconds),
    providing a short-lived consistency check for the confirmation loop.
    """
    # Check if confirmation is provided or globally skipped
    if confirm or os.getenv('MAGEMCP_SKIP_CONFIRMATION', '').lower() == 'true':
        return None
    
    # Generate a time-windowed token
    token = hashlib.sha256(f'{action}:{entity_id}:{int(time.time() // 300)}'.encode()).hexdigest()[:12]
    
    return {
        'confirmation_required': True,
        'action': action,
        'entity': entity_id,
        'message': f'This will {action} order {entity_id}. Call again with confirm=True to proceed.',
        'token': token,
    }
