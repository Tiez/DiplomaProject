# Diploma project Code runner       <!-- Main title -->
This is a leetcode like website that im working on for my diploma project. Reason i wanted to make this was in my country there is not much of information and good source in computer science field. For myself i was relatively familiar with english so i had no trouble finding the information i needed. But that was not the case for everyone. Because of the language barrier. This projects goal is to remove that language barrier and be the bridge for many ambitious mongolian youths who have big dreams.
## Features          <!-- Secondary -->
My Project features interactive way to learn coding and solving problems. Site runs you code snippet and uses custom made judge system using docker for isolation and safety. 
There will be many problems to solve as well as chance to compete against other users aswell. There will monthly hosted coding contest to engage and encourage our users.
### Installation     <!-- Sub-section -->
reqiurments

python 3.12ver
docker 4.50 ver
flask 3.1.2 ver
flask-login 0.6.3 ver
werkzeug 3.1.3 ver
flask-wtf 1.2.2 ver
wtforms 3.2.1 ver
psutil 7.0.0 ver

To run this project in parent folder of project, folder named "sandbox" is required

Step 1:
1. First create a virtual enviroment. To do that run following command ```sudo apt install -y python3-venv```
2. Navigate to project folder then run ```python3 -m venv venv```
3. Then activate the enviroment with ```source venv/bin/activate``` and install all required packages with following code
   ```pip install flask==3.1.2 flask-login==0.6.3 werkzeug==3.1.3 flask-wtf==1.2.2 wtforms==3.2.1 psutil==7.0.0```

Step 2:
Download and install docker:

On linux:
  1. Install prerequisites ```sudo dnf -y install dnf-plugins-core```
  2. Add Docker repository ```sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo```
  3. Install Docker ```sudo dnf install docker-ce docker-ce-cli containerd.io docker-compose-plugin```
  4. Start docker ```sudo systemctl start docker / sudo systemctl enable docker```

Verify installation with this command sudo docker run hello-world

On windows:
  1. Download and install docker from oficial website https://docs.docker.com/desktop/setup/install/windows-install/
  2. Restart your pc after installation

Step 3:
Build docker image in main DiplomaProject folder with dockerfile. Name must be "python-sandbox"
Build image with following command in console ```docker build -t python-sandbox .```


Step 4:
run server by running run.py in console ```python run.py```. Make sure virtual enviroment is still active
