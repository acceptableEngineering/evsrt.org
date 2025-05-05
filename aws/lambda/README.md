# Lambda Functions

## Development
```
# Navigate to your Lambda source dir
cd ./discord-reminder-bot/

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip and install requirements into local 'package' dir
python -m pip install --upgrade pip

# Install requirements
pip3 install -r requirements.txt

# Did you change the requirements? Make sure to freeze
pip3 freeze > requirements.txt

# When done
deactivate
```
