"""Observe accepted FSM transitions, never message bodies."""
from aiogram import BaseMiddleware
from analytics import emit


class FunnelMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        state = data.get('state')
        analytics = data.get('analytics')
        before = await state.get_data() if state else {}
        current = await state.get_state() if state else None
        step = current.split(':')[-1] if current and current.startswith('RegistrationState:') else None
        is_cancel = getattr(event, 'data', None) in {'reg_cancel', 'cancel_registration'} or (
            (getattr(event, 'text', None) or '').split('@')[0].strip() == '/cancel')
        try:
            result = await handler(event, data)
        except Exception:
            if step:
                emit(analytics, 'registration_failed', event.from_user.id, before,
                     step, 'handler_error')
            raise
        after = await state.get_data() if state else {}
        next_state = await state.get_state() if state else None
        if step and before.get('attempt_id'):
            if is_cancel:
                emit(analytics, 'registration_cancelled', event.from_user.id,
                     before, step, 'cancelled', key=f"{before['attempt_id']}:terminal")
            elif (before.get('attempt_id') == after.get('attempt_id') and
                  next_state != current and next_state and next_state.startswith('RegistrationState:')):
                if getattr(event, 'data', None) == 'edit_registration':
                    emit(analytics, 'registration_step_completed', event.from_user.id,
                         {**before, **after}, step, 'edited')
                else:
                    emit(analytics, 'registration_step_completed', event.from_user.id,
                         {**before, **after}, step)
        return result
