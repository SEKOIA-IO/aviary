#!/bin/bash

TEST_WORK=true
TEST_FAIL=true
TEST_FAIL_IN_METRICS=true
TEST_DIRECT=true
TEST_SCALE=true


green=$(tput setaf 2)
default=$(tput sgr0)

#copy testing configuration to right location
mkdir python/config
cp resources/tests/canaries.yaml python/config/canaries.yaml

#cleanup previous testing material
kubectl --namespace sic --context test-sekoia-io delete deployment aviary-tester aviary-tester-primary aviary-tester-canary
sleep 2
kubectl --namespace sic --context test-sekoia-io apply -f resources/tests/deploy/deploy-original.yaml
sleep 2

#setup logging
now=`date +"%Y-%m-%d-%s"`
python -u python/aviary.py | tee "aviary-${now}.log" | sed "s/.*/$green&$default/" &

#wait for all 3 deployments to exist
next=`kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester | wc -l`
while [[ $next != "3" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester | wc -l`
done
sleep 1
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester

#wait for the 5 primary pods to be ready, and the only ones running
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
done

#setup is done, any test can be run from here
echo "SETUP DONE"
sleep 1


#tests the nominal case, a perfectly working canary release, triggered by an image change
if $TEST_WORK; then

kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester
echo
echo ">>> DEPLOYING NEW, WORKING VERSION"
echo
kubectl --namespace sic --context test-sekoia-io apply -f resources/tests/deploy/deploy-work.yaml


#wait until the primary deployment gets the last image, last step of a successful deployment
next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest`
while [[ -z $next ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest`
    kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest
done

#check final replica count
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
done
echo
echo ">>> CANARY-WORK TEST CASE SUCCEEDED"
echo
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester
kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest

fi

#tests the rolling back of a deployment if some of the new pods restarts
if $TEST_FAIL; then

echo
echo ">>> DEPLOYING NEW, HARD FAILING VERSION (restarts)"
echo
kubectl --namespace sic --context test-sekoia-io apply -f resources/tests/deploy/deploy-fail.yaml

#wait for primary to be rolled back to non-failing
next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester -o yaml | grep " fail"`
until [[ -z $next ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester -o yaml | grep " fail"`
done

echo "OG deploy rolledback"

#check final replica count
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
done
echo
echo ">>> CANARY-FAIL TEST CASE SUCCEEDED"
echo
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester
kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest

fi

sleep 1

#tests the rolling back of a deployment if some of the new pods report metrics in error
if $TEST_FAIL_IN_METRICS; then
echo
echo ">>> DEPLOYING NEW, FAILING IN METRICS VERSION"
echo
kubectl --namespace sic --context test-sekoia-io apply -f resources/tests/deploy/deploy-fail-in-metrics.yaml

#wait for primary to be rolled back to non-failing
next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester -o yaml | grep " fail-in-metrics"`
until [[ -z $next ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester -o yaml | grep " fail-in-metrics"`
done

#check final replica count
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
done
echo
echo ">>> CANARY-FAIL-IN-METRICS TEST CASE SUCCEEDED"
echo
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester
kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest

fi

sleep 1

if $TEST_DIRECT; then
echo
echo ">>> DEPLOYING NEW, WORKING DEPLOYMENT WITH NEW UNWATCHED FIELD (direct deployment)"
echo
kill %1
kubectl --namespace sic --context test-sekoia-io apply -f resources/tests/deploy/deploy-original.yaml
python -u python/aviary.py | tee -a "aviary-${now}.log" | sed "s/.*/$green&$default/" &
#wait for all 3 deployments to exist
next=`kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester | wc -l`
while [[ $next != "3" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester | wc -l`
done
sleep 1
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester

#wait for the 5 primary pods to be ready, and the only ones running
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester | wc -l`
done
echo "SETUP DONE"

sleep 1

kubectl --namespace sic --context test-sekoia-io apply -f resources/tests/deploy/deploy-direct.yaml

#check final replica count
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
done

#wait for primary to get the new label
next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep "terminationGracePeriod"`
while [[ -z $next ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep "terminationGracePeriod"`
done

#check final replica count
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester | wc -l`
while [[ $next != "5" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester | wc -l`
done

echo
echo ">>> CANARY-DIRECT-DEPLOY TEST CASE SUCCEEDED"
echo
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester
kubectl --namespace sic --context test-sekoia-io get deploy aviary-tester-primary -o yaml | grep aviary-tester:latest

fi

if $TEST_SCALE; then
echo
echo ">>> SCALING ORIGINAL DEPLOYMENT TO 9 INSTANCES"
echo
kubectl --namespace sic --context test-sekoia-io scale deploy aviary-tester --replicas=9

#wait for the 9 primary pods to be ready, and the only ones running
next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
while [[ $next != "9" ]]
do
    sleep 1
    next=`kubectl --namespace sic --context test-sekoia-io get pods | grep aviary-tester-primary | wc -l`
done

echo
echo ">>> CANARY-SCALE TEST CASE SUCCEEDED"
echo
kubectl --namespace sic --context test-sekoia-io get deploy | grep aviary-tester

sleep 1
fi

echo "DONE"

kill %1

echo "CLEANING UP"
kubectl --namespace sic --context test-sekoia-io delete deployment aviary-tester aviary-tester-primary aviary-tester-canary

