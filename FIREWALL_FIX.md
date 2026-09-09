# Quick Fix: Open Oracle Cloud Firewall

Your backend is running on the VM but the ports are blocked.

## Option 1: Oracle Console (5 minutes)

1. Go to https://cloud.oracle.com
2. Menu → Compute → Instances
3. Click on `hermes-node`
4. Find the **VNIC** section, click the subnet name
5. Click the **Security List** name
6. Click **Add Ingress Rules** and add:

| Source CIDR | IP Protocol | Destination Port |
|-------------|-------------|------------------|
| 0.0.0.0/0   | TCP         | 8000             |
| 0.0.0.0/0   | TCP         | 8777             |
| 0.0.0.0/0   | TCP         | 5173             |

7. Click **Add ingress rules**

## Option 2: CLI (if you have oci cli installed)

```bash
# Get your security list OCID
oci network security-list list --compartment-id <your-compartment>

# Add ingress rule for port 8000
oci network security-list create-egress-rule \
  --security-list-id <SL_OCID> \
  --state ENABLED \
  --protocol tcp \
  --destination 0.0.0.0/0 \
  --destination-type CIDR_BLOCK \
  --dst-port-range '{"min":8000,"max":8000}'

# Same for 8777 and 5173
```

## After opening ports

Test from your local machine:

```bash
curl http://158.180.57.167:8000/api/health
curl http://158.180.57.167:8777/health
```

## Frontend URL

Once ports are open, deploy frontend to point at the API:

```bash
cd frontend
VITE_API_URL=http://158.180.57.167:8000 \
VITE_VENDOR_URL=http://158.180.57.167:8777 \
npx vercel --prod --yes
```
