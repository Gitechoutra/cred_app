"""
Saving customer documents - KYC proofs, income proofs - to the upload folder.

Files are stored under random names and never served statically. The only way
back out is an audited, role-gated admin route that looks the path up in the
database, so a leaked filename is worthless on its own.
"""

import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

from portal.helpers.validators import ValidationError

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}

#: What the admin routes may stream back, by extension. A stored file with any
#: other extension is refused rather than served with a guessed content type.
MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.pdf': 'application/pdf',
}


def save_document(upload, folder: str, user_id: str, label: str) -> str:
    """
    Persist an uploaded document under a random filename, and return its path
    relative to UPLOAD_FOLDER. None when nothing was uploaded.

    The uploaded name is attacker-controlled and may carry a path or a
    misleading extension, so only the validated extension is reused.
    """
    if not upload or not upload.filename:
        return None

    extension = os.path.splitext(secure_filename(upload.filename))[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError('Upload a PDF or an image (JPG, PNG).', label)

    target = os.path.join(current_app.config['UPLOAD_FOLDER'], folder, str(user_id))
    os.makedirs(target, exist_ok=True)

    filename = f'{label}_{uuid.uuid4().hex}{extension}'
    upload.save(os.path.join(target, filename))

    return os.path.join(folder, str(user_id), filename).replace('\\', '/')


def remove_document(stored: str) -> None:
    """Delete a saved document, when the request that saved it failed."""
    if not stored:
        return
    try:
        os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], stored))
    except OSError:
        pass


def resolve(stored: str):
    """
    The absolute path and MIME type of a stored document, or (None, reason).

    Refuses anything that resolves outside the upload root. The path comes from
    our own database, so it should already be safe - but a stored value
    corrupted by some future bug must not become an arbitrary file read.
    """
    upload_root = os.path.realpath(current_app.config['UPLOAD_FOLDER'])
    resolved = os.path.realpath(os.path.join(upload_root, stored))
    if not resolved.startswith(upload_root + os.sep):
        return None, 'outside'
    if not os.path.isfile(resolved):
        return None, 'missing'
    mimetype = MIME_TYPES.get(os.path.splitext(resolved)[1].lower())
    if not mimetype:
        return None, 'type'
    return (resolved, mimetype), None
