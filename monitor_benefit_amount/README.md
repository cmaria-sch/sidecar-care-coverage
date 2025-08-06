## FOR DEPLOYING INTO DEV...
#### Set AWS environment to DEV and run the below commands.
``` Bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 359879675385.dkr.ecr.us-east-1.amazonaws.com
docker build --platform linux/amd64 -t 359879675385.dkr.ecr.us-east-1.amazonaws.com/sidecar-data-monitor-benefit-amount:latest .
docker push 359879675385.dkr.ecr.us-east-1.amazonaws.com/sidecar-data-monitor-benefit-amount:latest
```
## FOR DEPLOYING INTO QA...
#### Set AWS environment to DEV and run the below commands. This is because we use DEV ECR repo for QA.
``` Bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 359879675385.dkr.ecr.us-east-1.amazonaws.com
docker build --platform linux/amd64 -t 359879675385.dkr.ecr.us-east-1.amazonaws.com/sidecar-data-pricing-npi-to-location:qa_release .
docker push 359879675385.dkr.ecr.us-east-1.amazonaws.com/sidecar-data-pricing-npi-to-location:qa_release
```

# for publishing changes in prod
## FOR DEPLOYING INTO PROD...
#### Set AWS environment to DEV and run the below commands. This is because we use DEV ECR repo for QA.
``` Bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 359879675385.dkr.ecr.us-east-1.amazonaws.com
docker build --platform linux/amd64 -t 359879675385.dkr.ecr.us-east-1.amazonaws.com/sidecar-data-pricing-npi-to-location:latest .
docker push 359879675385.dkr.ecr.us-east-1.amazonaws.com/sidecar-data-pricing-npi-to-location:latest
```
