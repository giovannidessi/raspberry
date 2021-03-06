#!/bin/bash
#https://dev.to/elalemanyo/how-to-install-docker-and-docker-compose-on-raspberry-pi-1mo

sudo apt-get update && sudo apt-get upgrade
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker pi

sudo apt-get install libffi-dev libssl-dev
sudo apt install python3-dev
sudo apt-get install -y python3 python3-pip
sudo pip3 install docker-compose
sudo systemctl enable docker
sudo gpasswd -a $USER docker
sudo chmod 666 /var/run/docker.sock
