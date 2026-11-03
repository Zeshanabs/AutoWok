# Credential storage and key rotation

## Stored credentials

- Social account Page tokens and Meta user tokens are encrypted with Fernet using `TOKEN_ENCRYPTION_KEY`.
- Workspace AI provider keys are encrypted with Fernet using `AI_ENCRYPTION_KEY`.
- Optional `*_PREVIOUS` keys allow decryption of records encrypted before rotation. New credentials are always encrypted with the current primary key.
- Only encrypted values are persisted. API responses, logs, audit metadata, and the frontend do not expose token values.
- Fernet keys are high-impact secrets. Keep them in an ignored local `.env` for development and in a deployment secret manager for production. Do not commit keys, send them to the browser, or include them in logs or support dumps.

Generate a key in the backend environment:

```powershell
cd backend
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Rotate encryption keys

The backend includes `scripts/rotate_encryption_keys.py`. It requires the new key as the primary key and the old key as `*_PREVIOUS`; it decrypts and re-encrypts the selected credential records in one database transaction. A failure rolls back the transaction. Back up the database and keep the old key safely available until verification is complete.

For Meta credentials:

1. Set the new key as `TOKEN_ENCRYPTION_KEY` and the old key as `TOKEN_ENCRYPTION_KEY_PREVIOUS`.
2. Run a dry run, then rotate:

   ```powershell
   cd backend
   python scripts/rotate_encryption_keys.py --scope meta --dry-run
   python scripts/rotate_encryption_keys.py --scope meta
   ```

3. Verify OAuth discovery and account token checks in a controlled environment. Remove `TOKEN_ENCRYPTION_KEY_PREVIOUS` only after all stored Meta tokens have been re-encrypted and the new key has been backed up.

For AI provider credentials, use the same sequence with `AI_ENCRYPTION_KEY`, `AI_ENCRYPTION_KEY_PREVIOUS`, and `--scope ai`. Use `--scope all` only when both key pairs are configured correctly. The dry run verifies that all selected records can be decrypted but does not commit ciphertext changes.

Do not delete or replace the old key before rotation: credentials encrypted only under that key would become unrecoverable. Store protected key backups separately from database backups and restrict access to both.

If a key may have been disclosed, rotate it promptly, review access to the relevant secret manager and database, and reauthorize external accounts if token exposure is suspected. Fernet encryption at rest does not protect secrets from a compromised running backend or an operator with access to both the database and encryption keys.
