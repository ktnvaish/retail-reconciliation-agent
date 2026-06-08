# Deploying to Azure Container Apps

This guide deploys the ReconcileFlow Agent as a **single-replica** container on
[Azure Container Apps](https://learn.microsoft.com/azure/container-apps/) with a
public HTTPS URL — ideal for a shareable demo.

> **Why single replica?** The demo persists state in a local SQLite file, which
> is single-writer. Horizontal scale would require an external database
> (Postgres) — see "Next steps".

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az version` ≥ 2.60)
- An Azure subscription
- A [Groq API key](https://console.groq.com/) (for the real LLM)
- A [Resend API key](https://resend.com/) **with a verified sending domain**
  (for real email delivery)

## 1. Sign in and set defaults

```bash
az login
az account set --subscription "<your-subscription>"

az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

## 2. Create a resource group and environment

```bash
RG=reconcileflow-rg
LOCATION=centralindia
ENV=reconcileflow-env

az group create --name $RG --location $LOCATION
az containerapp env create --name $ENV --resource-group $RG --location $LOCATION
```

## 3. Deploy from source (build happens in Azure)

`az containerapp up` builds the image from the local `Dockerfile` (using ACR
build) and deploys it in one step:

```bash
az containerapp up \
  --name reconcileflow \
  --resource-group $RG \
  --environment $ENV \
  --source . \
  --ingress external \
  --target-port 8000
```

The command prints the public URL, e.g.
`https://reconcileflow.<hash>.<region>.azurecontainerapps.io`.

## 4. Configure secrets and environment

Store secrets as Container Apps **secrets**, then reference them as env vars.
Recipients are set via `RECIPIENT_*` so real addresses never enter the repo.

```bash
az containerapp secret set \
  --name reconcileflow --resource-group $RG \
  --secrets groq-key=<GROQ_API_KEY> resend-key=<RESEND_API_KEY> demo-key=<CHOOSE_A_KEY>

az containerapp update \
  --name reconcileflow --resource-group $RG \
  --min-replicas 1 --max-replicas 1 \
  --set-env-vars \
    MOCK_LLM=false \
    NOTIFIER=resend \
    GROQ_API_KEY=secretref:groq-key \
    RESEND_API_KEY=secretref:resend-key \
    RESEND_FROM="alerts@yourdomain.com" \
    DEMO_ACCESS_KEY=secretref:demo-key \
    RECIPIENT_STORE_MANAGER="you+store@yourdomain.com" \
    RECIPIENT_ADMIN="you+admin@yourdomain.com" \
    RECIPIENT_BANK="you+bank@yourdomain.com" \
    RECIPIENT_PG_RAZORPAY="you+razorpay@yourdomain.com" \
    RECIPIENT_PG_PAYU="you+payu@yourdomain.com" \
    RECIPIENT_PG_CASHFREE="you+cashfree@yourdomain.com"
```

> Keep `--min-replicas 1 --max-replicas 1`. To send real email, point every
> `RECIPIENT_*` at inboxes **you control** and use a Resend-verified `RESEND_FROM`
> domain — otherwise messages bounce.

## 5. Verify

```bash
APP_URL=$(az containerapp show --name reconcileflow --resource-group $RG \
  --query properties.configuration.ingress.fqdn -o tsv)

curl "https://$APP_URL/healthz"          # {"status":"ok"}
open "https://$APP_URL"                    # upload UI (or visit in a browser)
```

Stream logs (structured JSON):

```bash
az containerapp logs show --name reconcileflow --resource-group $RG --follow
```

## 6. Tear down

```bash
az group delete --name $RG --yes --no-wait
```

## Notes on hosted state

`DATA_DIR` (SQLite, incidents, mock outbox) lives on the container's **ephemeral**
disk and resets on restart/redeploy — acceptable for a demo. For durability,
mount an [Azure Files share](https://learn.microsoft.com/azure/container-apps/storage-mounts)
at `DATA_DIR`.

## Next steps (production)

- External Postgres + Alembic migrations to allow multiple replicas.
- CI/CD: GitHub Actions → ACR build → `az containerapp update` on push to `main`.
- Front the app with auth (Azure Container Apps supports built-in auth providers).
