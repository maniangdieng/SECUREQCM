#!/usr/bin/env bash
# Crée l'infrastructure AWS de Secure QCM. À lancer UNE fois dans AWS CloudShell (région choisie).
# Voir docs/DEPLOIEMENT_AWS.md.
#
#   - un serveur EC2 (Ubuntu 24.04) avec une IP fixe, ports 80 et 443 seulement (pas de SSH) ;
#   - l'accès d'administration passe par AWS Systems Manager (Session Manager) ;
#   - un rôle que GitHub Actions peut prendre (OIDC, sans clé stockée) pour déployer à chaque push sur main.
#
# Aucun secret n'est créé ici : la clé Django et le mot de passe PostgreSQL sont générés sur le serveur
# (deploy/aws/server-setup.sh) et n'en sortent pas.
set -euo pipefail

REGION="${REGION:-eu-north-1}"
REPO="${REPO:-maniangdieng/SECUREQCM}"
INSTANCE_TYPE="${INSTANCE_TYPE:-c7i-flex.large}"   # 2 vCPU, 4 Go ; inclus dans l'offre gratuite
DISK_GB="${DISK_GB:-30}"
NAME=secureqcm
export AWS_DEFAULT_REGION="$REGION"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "Compte $ACCOUNT, région $REGION"

# --- 1. Rôle du serveur : Systems Manager uniquement ------------------------------------------
if ! aws iam get-role --role-name "$NAME-ec2" >/dev/null 2>&1; then
  aws iam create-role --role-name "$NAME-ec2" --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }' >/dev/null
  aws iam attach-role-policy --role-name "$NAME-ec2" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam create-instance-profile --instance-profile-name "$NAME-ec2" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$NAME-ec2" --role-name "$NAME-ec2"
  echo "Rôle du serveur créé ; attente de sa propagation…"
  sleep 15
fi

# --- 2. Pare-feu : HTTP (certificat + redirection) et HTTPS ------------------------------------
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$NAME-web" Name=vpc-id,Values="$VPC" \
     --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name "$NAME-web" --vpc-id "$VPC" \
       --description "Secure QCM : HTTP et HTTPS" --query GroupId --output text)
  for port in 80 443; do
    aws ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions \
      "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]" >/dev/null
  done
fi
echo "Pare-feu : $SG"

# --- 3. IP fixe, puis adresse sslip.io qui en dérive --------------------------------------------
ALLOC=$(aws ec2 describe-addresses --filters Name=tag:Name,Values="$NAME" --query 'Addresses[0].AllocationId' --output text)
if [ "$ALLOC" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc \
          --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
fi
IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)
HOST="${SITE_ADDRESS:-${IP//./-}.sslip.io}"
echo "IP fixe : $IP — adresse du site : https://$HOST"

# --- 4. Serveur -----------------------------------------------------------------------------------
INSTANCE=$(aws ec2 describe-instances --filters Name=tag:Name,Values="$NAME" \
           Name=instance-state-name,Values=pending,running,stopping,stopped \
           --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$INSTANCE" = "None" ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
        --query Parameter.Value --output text)
  USERDATA=$(mktemp)
  { echo '#!/bin/bash'; echo "export SITE_ADDRESS='$HOST' REPO='$REPO'"
    curl -fsSL "https://raw.githubusercontent.com/$REPO/${SETUP_REF:-main}/deploy/aws/server-setup.sh"; } > "$USERDATA"
  INSTANCE=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
    --security-group-ids "$SG" --iam-instance-profile Name="$NAME-ec2" \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Encrypted=true}" \
    --user-data "file://$USERDATA" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
    --query 'Instances[0].InstanceId' --output text)
  rm -f "$USERDATA"
  echo "Serveur $INSTANCE lancé ; attente du démarrage…"
  aws ec2 wait instance-running --instance-ids "$INSTANCE"
fi
aws ec2 associate-address --instance-id "$INSTANCE" --allocation-id "$ALLOC" >/dev/null
echo "Serveur : $INSTANCE"

# --- 5. Déploiement depuis GitHub Actions (OIDC, sans clé) --------------------------------------
OIDC="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
fi
TRUST=$(cat <<EOF
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
  "Principal": {"Federated": "$OIDC"}, "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {"StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                 "token.actions.githubusercontent.com:sub": "repo:$REPO:ref:refs/heads/main"}}}]}
EOF
)
if aws iam get-role --role-name "$NAME-github-deploy" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$NAME-github-deploy" --policy-document "$TRUST"
else
  aws iam create-role --role-name "$NAME-github-deploy" --assume-role-policy-document "$TRUST" \
    --description "GitHub Actions ($REPO, branche main) : deploie Secure QCM" >/dev/null
fi
# Seuls droits : lancer une commande sur CE serveur et en lire le résultat.
aws iam put-role-policy --role-name "$NAME-github-deploy" --policy-name deploy --policy-document "$(cat <<EOF
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ssm:SendCommand", "Resource": [
    "arn:aws:ec2:$REGION:$ACCOUNT:instance/$INSTANCE",
    "arn:aws:ssm:$REGION::document/AWS-RunShellScript"]},
  {"Effect": "Allow", "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"], "Resource": "*"}]}
EOF
)"

cat <<EOF

=== Terminé ===
Site (prêt dans 5 à 10 minutes, le temps d'installer Docker et de construire l'image) :
  https://$HOST
À enregistrer dans GitHub (Settings → Secrets and variables → Actions → Variables) :
  AWS_REGION=$REGION
  AWS_INSTANCE_ID=$INSTANCE
  AWS_DEPLOY_ROLE_ARN=arn:aws:iam::$ACCOUNT:role/$NAME-github-deploy
EOF
