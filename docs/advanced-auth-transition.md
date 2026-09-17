# Advanced API signing authority transition

The advanced API requires an explicitly configured JWT signing key. It does not accept the repository's legacy fallback when advanced protected retrieval is enabled.

## Configuration

POSIX example:

```bash
export JWT_SECRET_KEY='<operator-managed-secret>'
```

PowerShell example:

```powershell
$env:JWT_SECRET_KEY = '<operator-managed-secret>'
```

Do not place the key in source control, Compose files, screenshots, validation transcripts, or grant manifests. Use the deployment secret manager/environment injection used by the operator.

At advanced-service startup call `AuthUtils.advanced_signing_config()` and fail startup if explicit signing authority is unavailable. The returned configuration is shared by the advanced issuer/verifier path; the key itself must not be logged.

## Existing-token transition

Changing the configured signing key invalidates tokens signed under the previous authority. Before enabling advanced protected retrieval with a new key:

1. configure the new operator-managed key on every advanced API instance;
2. restart the advanced API instances so issuer and verifier use the same authority;
3. require users with older tokens to authenticate again and receive newly signed tokens;
4. do not temporarily accept both the repository fallback and the new key as an implicit compatibility mode;
5. verify invalid/expired/wrong-signature tokens still return authentication failure before enabling protected retrieval.

Legacy authentication routes are not broadly rewritten by Prompt 15. This transition requirement applies to the advanced protected-retrieval startup boundary.
