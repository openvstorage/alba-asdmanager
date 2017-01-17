# ALBA ASD manager
The ALBA ASD manager is a lightweight library exposing an API for easy setup and configuration management of the ALBA ASD's. It is not in the data path towards the disks, it's main purpose is to provide an easy way to:
* list the block devices in your node
* initialize them as an ASD (Alba Storage device)
* get the ip addresses of your storage node
* configure the storage ip address to be used
* restart an ASD
* etc .

The current methods exposed can be found in [api.py](source/app/api.py)

# Install
It's packaged as the Open vStorage Backend ASD Manager into **openvstorage-sdm**

    apt-get install openvstorage-sdm

Post install a very short setup needs to get completed to initialize it after which it will get automatically started

```
root@str06-grav:~# asd-manager setup
+++++++++++++++++++++++++++
+++  ASD Manager setup  +++
+++++++++++++++++++++++++++
- Verifying distribution
2016-06-16 19:28:30 94800 +0200 - str06-grav - 1532/140281988548416 - asd-manager/upstart - 0 - DEBUG - Service ovs-asd-manager could not be found.
Found exactly one choice: 6.196.87.55
Select the port to be used for the API [8500]: 
Select an IP address or all IP addresses to be used for the ASDs. Make a selection please: 
    1: 6.196.87.55
    2: All
  Select Nr:  [2]: 1
Do you want to add another IP? (y/n): n
Select the port to be used for the ASDs [8600]: 
- Starting watcher service
+++++++++++++++++++++++++++++++++++++
+++  ASD Manager setup completed  +++
+++++++++++++++++++++++++++++++++++++
```
