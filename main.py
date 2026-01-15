# app.py - COMPLETE FIXED VERSION
import os
import sys
import time
import json
import threading
import subprocess
import atexit
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

# Configuration
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production'),
    UPLOAD_FOLDER='uploads',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    ALLOWED_EXTENSIONS={'py', 'txt', 'json', 'env', 'yaml', 'yml', 'cfg', 'ini', 'js', 'html', 'css', 'md'},
    BOTS_FOLDER='bots',
    LOGS_FOLDER='logs',
    STATE_FILE='bot_state.json',
    CONFIG_FILE='bot_config.json'
)

# Create necessary directories
for folder in [app.config['UPLOAD_FOLDER'], app.config['BOTS_FOLDER'], app.config['LOGS_FOLDER']]:
    Path(folder).mkdir(exist_ok=True, parents=True)

# Store running bot processes
running_bots: Dict[str, Dict[str, Any]] = {}

class BotStateManager:
    """Manages persistent bot state"""
    
    def __init__(self, state_file: str, config_file: str):
        self.state_file = Path(state_file)
        self.config_file = Path(config_file)
        self.state: Dict[str, Any] = {}
        self.config: Dict[str, Any] = {}
        self.load_state()
        self.load_config()
        
    def load_state(self):
        """Load bot state from JSON file"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)
                logger.info(f"Loaded bot state from {self.state_file}")
            else:
                self.state = {
                    'bots': {},
                    'last_updated': datetime.now().isoformat(),
                    'server_start_time': datetime.now().isoformat()
                }
                self.save_state()
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            self.state = {'bots': {}, 'last_updated': datetime.now().isoformat()}
            
    def load_config(self):
        """Load bot configuration from JSON file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.info(f"Loaded bot config from {self.config_file}")
            else:
                self.config = {
                    'auto_start': True,
                    'max_concurrent_bots': 5,
                    'auto_restart_on_crash': False,
                    'settings': {
                        'log_retention_days': 7,
                        'backup_on_edit': True,
                        'notify_on_crash': False
                    }
                }
                self.save_config()
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self.config = {'auto_start': True}
    
    def save_state(self):
        """Save bot state to JSON file"""
        try:
            self.state['last_updated'] = datetime.now().isoformat()
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    def save_config(self):
        """Save bot configuration to JSON file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def update_bot_state(self, bot_id: str, status: str, auto_restart: bool = None, **kwargs):
        """Update state for a specific bot"""
        if 'bots' not in self.state:
            self.state['bots'] = {}
        
        if bot_id not in self.state['bots']:
            self.state['bots'][bot_id] = {
                'id': bot_id,
                'created_at': datetime.now().isoformat(),
                'status_history': []
            }
        
        bot_state = self.state['bots'][bot_id]
        bot_state['status'] = status
        bot_state['last_updated'] = datetime.now().isoformat()
        
        # Add to status history
        status_entry = {
            'status': status,
            'timestamp': datetime.now().isoformat(),
            **kwargs
        }
        
        if 'status_history' not in bot_state:
            bot_state['status_history'] = []
        
        bot_state['status_history'].append(status_entry)
        
        # Keep only last 50 status entries
        if len(bot_state['status_history']) > 50:
            bot_state['status_history'] = bot_state['status_history'][-50:]
        
        # Update auto_restart if provided
        if auto_restart is not None:
            bot_state['auto_restart'] = auto_restart
            
        # Update additional kwargs
        for key, value in kwargs.items():
            bot_state[key] = value
        
        self.save_state()
    
    def get_bot_state(self, bot_id: str) -> Dict[str, Any]:
        """Get state for a specific bot"""
        return self.state.get('bots', {}).get(bot_id, {})
    
    def get_all_bots_state(self) -> Dict[str, Any]:
        """Get state for all bots"""
        return self.state.get('bots', {})
    
    def remove_bot_state(self, bot_id: str):
        """Remove state for a bot"""
        if 'bots' in self.state and bot_id in self.state['bots']:
            del self.state['bots'][bot_id]
            self.save_state()
    
    def get_auto_start_bots(self) -> List[str]:
        """Get list of bots that should auto-start"""
        auto_start_bots = []
        for bot_id, bot_state in self.state.get('bots', {}).items():
            if bot_state.get('auto_restart', True) and bot_state.get('status') == 'running':
                auto_start_bots.append(bot_id)
        return auto_start_bots
    
    def set_config(self, key: str, value: Any):
        """Set configuration value"""
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self.save_config()
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        keys = key.split('.')
        config = self.config
        for k in keys:
            if k not in config:
                return default
            config = config[k]
        return config

# Initialize state manager
state_manager = BotStateManager(
    app.config['STATE_FILE'],
    app.config['CONFIG_FILE']
)

def get_python_executable():
    """Get the correct Python executable path"""
    if sys.platform == 'win32':
        pythonw_path = sys.executable
        if pythonw_path.endswith('pythonw.exe'):
            python_path = pythonw_path.replace('pythonw.exe', 'python.exe')
            if os.path.exists(python_path):
                return python_path
    return sys.executable

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_absolute_path(relative_path):
    return Path(__file__).parent.absolute() / relative_path

def run_bot(bot_id: str, bot_path: Path):
    """Run bot with proper encoding handling"""
    log_path = get_absolute_path(app.config['LOGS_FOLDER']) / f"{bot_id}.log"
    python_executable = get_python_executable()
    
    log_path.parent.mkdir(exist_ok=True, parents=True)
    
    # Create an environment with UTF-8 encoding
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    
    try:
        with open(log_path, 'w', encoding='utf-8', errors='ignore') as log_file:
            log_file.write(f"[{datetime.now()}] Starting bot: {bot_id}\n")
            log_file.write(f"[{datetime.now()}] Python executable: {python_executable}\n")
            log_file.write(f"[{datetime.now()}] Working directory: {bot_path}\n")
            log_file.flush()
            
            # Find Python file
            python_files = []
            for file in bot_path.iterdir():
                if file.is_file() and file.suffix == '.py':
                    python_files.append(file)
            
            if not python_files:
                log_file.write(f"[{datetime.now()}] Error: No Python files found\n")
                state_manager.update_bot_state(bot_id, 'error', error='No Python files found')
                return
            
            # Check for common main file names first
            main_script = None
            common_names = ['main.py', 'bot.py', 'app.py', 'run.py', 'start.py']
            for name in common_names:
                for file in python_files:
                    if file.name.lower() == name:
                        main_script = file
                        break
                if main_script:
                    break
            
            # If no common name found, use the first Python file
            if not main_script:
                main_script = python_files[0]
            
            log_file.write(f"[{datetime.now()}] Using script: {main_script.name}\n")
            
            # Install requirements if exists
            requirements_file = bot_path / 'requirements.txt'
            if requirements_file.exists():
                try:
                    log_file.write(f"[{datetime.now()}] Installing dependencies...\n")
                    result = subprocess.run(
                        [python_executable, "-m", "pip", "install", "-r", "requirements.txt"],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore',
                        cwd=str(bot_path),
                        env=env
                    )
                    if result.returncode == 0:
                        log_file.write(f"[{datetime.now()}] Dependencies installed successfully\n")
                    else:
                        log_file.write(f"[{datetime.now()}] Failed to install dependencies\n")
                        if result.stderr:
                            log_file.write(f"Error: {result.stderr[:500]}\n")
                    log_file.flush()
                except Exception as e:
                    log_file.write(f"[{datetime.now()}] Error installing dependencies: {str(e)}\n")
            
            # Run bot with proper encoding
            try:
                log_file.write(f"[{datetime.now()}] Running command: {python_executable} {main_script.name}\n")
                log_file.flush()
                
                process = subprocess.Popen(
                    [python_executable, str(main_script.name)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    cwd=str(bot_path),
                    env=env,
                    bufsize=1,
                    shell=True if sys.platform == 'win32' else False
                )
                
                running_bots[bot_id] = {
                    'process': process,
                    'start_time': datetime.now(),
                    'log_path': str(log_path),
                    'bot_path': str(bot_path),
                    'pid': process.pid if hasattr(process, 'pid') else None
                }
                
                # Update state
                state_manager.update_bot_state(
                    bot_id, 
                    'running',
                    pid=process.pid if hasattr(process, 'pid') else None,
                    start_time=datetime.now().isoformat(),
                    command=f"{python_executable} {main_script.name}"
                )
                
                log_file.write(f"[{datetime.now()}] Bot process started\n")
                log_file.flush()
                
                # Read output in real-time
                for line in iter(process.stdout.readline, ''):
                    if line:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        log_line = f"[{timestamp}] {line}"
                        log_file.write(log_line)
                        log_file.flush()
                
                process.wait()
                return_code = process.returncode
                log_file.write(f"[{datetime.now()}] Bot process ended with code: {return_code}\n")
                
                # Update state based on exit code
                if return_code == 0:
                    state_manager.update_bot_state(bot_id, 'stopped', exit_code=return_code)
                else:
                    state_manager.update_bot_state(bot_id, 'crashed', exit_code=return_code)
                
            except Exception as e:
                log_file.write(f"[{datetime.now()}] Error running bot: {str(e)}\n")
                state_manager.update_bot_state(bot_id, 'error', error=str(e))
            finally:
                if bot_id in running_bots:
                    del running_bots[bot_id]
    except Exception as e:
        logger.error(f"Error in run_bot for {bot_id}: {e}")
        state_manager.update_bot_state(bot_id, 'error', error=str(e))

def start_bot_persistent(bot_id: str, auto_restart: bool = True):
    """Start a bot and save persistent state"""
    bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
    if not bot_path.exists():
        return False, "Bot not found"
    
    # Check if already running
    if bot_id in running_bots:
        return False, "Bot is already running"
    
    # Check if there are Python files
    python_files = [f for f in bot_path.iterdir() if f.is_file() and f.suffix == '.py']
    if not python_files:
        return False, "No Python files found in bot directory"
    
    # Update state before starting
    state_manager.update_bot_state(bot_id, 'starting', auto_restart=auto_restart)
    
    # Start bot in background
    bot_thread = threading.Thread(
        target=run_bot,
        args=(bot_id, bot_path),
        daemon=True
    )
    bot_thread.start()
    
    # Give it a moment to start
    time.sleep(0.5)
    
    return True, f"Bot {bot_id} started"

def stop_bot_persistent(bot_id: str):
    """Stop a bot and save persistent state"""
    if bot_id not in running_bots:
        return False, "Bot is not running"
    
    bot_info = running_bots[bot_id]
    process = bot_info['process']
    
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except Exception as e:
        logger.error(f"Error stopping bot {bot_id}: {e}")
    
    if bot_id in running_bots:
        del running_bots[bot_id]
    
    # Update state
    state_manager.update_bot_state(bot_id, 'stopped', stopped_by='user')
    
    return True, f"Bot {bot_id} stopped"

def auto_start_bots():
    """Auto-start bots based on saved state"""
    auto_start_bots_list = state_manager.get_auto_start_bots()
    
    if not auto_start_bots_list:
        logger.info("No bots configured for auto-start")
        return
    
    logger.info(f"Auto-starting {len(auto_start_bots_list)} bots")
    
    for bot_id in auto_start_bots_list:
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        if bot_path.exists():
            # Start in background thread with delay
            time.sleep(0.5)
            
            thread = threading.Thread(
                target=run_bot,
                args=(bot_id, bot_path),
                daemon=True
            )
            thread.start()
            logger.info(f"Auto-started bot: {bot_id}")
        else:
            logger.warning(f"Bot directory not found: {bot_id}")

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Main dashboard"""
    bots = []
    bots_folder = get_absolute_path(app.config['BOTS_FOLDER'])
    
    if bots_folder.exists():
        for bot_dir in bots_folder.iterdir():
            if bot_dir.is_dir():
                bot_state = state_manager.get_bot_state(bot_dir.name)
                
                # Determine current status
                current_status = 'running' if bot_dir.name in running_bots else 'stopped'
                if bot_state:
                    current_status = bot_state.get('status', current_status)
                
                # Get files
                try:
                    files = [f.name for f in bot_dir.iterdir() if f.is_file()]
                except:
                    files = []
                
                bot_info = {
                    'id': bot_dir.name,
                    'name': bot_dir.name,
                    'status': current_status,
                    'created_at': datetime.fromtimestamp(bot_dir.stat().st_ctime).strftime('%Y-%m-%d %H:%M'),
                    'files': files,
                    'has_py': any(f.suffix == '.py' for f in bot_dir.iterdir() if f.is_file()),
                    'auto_restart': bot_state.get('auto_restart', False) if bot_state else False,
                    'last_updated': bot_state.get('last_updated') if bot_state else None
                }
                bots.append(bot_info)
    
    # Sort bots by status (running first)
    bots.sort(key=lambda x: 0 if x['status'] == 'running' else 1)
    
    return render_template('index.html', 
                         bots=bots, 
                         auto_start_enabled=state_manager.get_config('auto_start', True))

@app.route('/upload', methods=['GET', 'POST'])
def upload_bot():
    """Upload bot files"""
    if request.method == 'POST':
        if 'files[]' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files[]')
        bot_name = request.form.get('bot_name', '').strip()
        auto_restart = request.form.get('auto_restart', 'false') == 'true'
        
        if not bot_name:
            bot_name = f"bot_{int(time.time())}"
        
        bot_id = secure_filename(bot_name.replace(' ', '_'))
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        bot_path.mkdir(exist_ok=True, parents=True)
        
        uploaded_files = []
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file_path = bot_path / filename
                try:
                    file.save(file_path)
                    uploaded_files.append(filename)
                except Exception as e:
                    logger.error(f"Error saving file {filename}: {e}")
        
        # Initialize bot state
        state_manager.update_bot_state(
            bot_id, 
            'stopped', 
            auto_restart=auto_restart,
            files=uploaded_files
        )
        
        return jsonify({
            'success': True,
            'bot_id': bot_id,
            'message': f'Uploaded {len(uploaded_files)} files',
            'files': uploaded_files,
            'auto_restart': auto_restart
        })
    
    return render_template('upload.html')

@app.route('/bot/<bot_id>/start', methods=['POST'])
def start_bot(bot_id):
    """Start a bot"""
    try:
        data = request.get_json() or {}
        auto_restart = data.get('auto_restart', True)
        
        success, message = start_bot_persistent(bot_id, auto_restart)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'auto_restart': auto_restart
            })
        else:
            return jsonify({'error': message}), 400
    except Exception as e:
        logger.error(f"Error in start_bot: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/stop', methods=['POST'])
def stop_bot_route(bot_id):
    """Stop a running bot"""
    try:
        success, message = stop_bot_persistent(bot_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 400
    except Exception as e:
        logger.error(f"Error in stop_bot: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/restart', methods=['POST'])
def restart_bot(bot_id):
    """Restart a bot"""
    try:
        # Stop if running
        if bot_id in running_bots:
            stop_bot_persistent(bot_id)
            time.sleep(1)
        
        # Start again
        bot_state = state_manager.get_bot_state(bot_id)
        auto_restart = bot_state.get('auto_restart', True) if bot_state else True
        
        success, message = start_bot_persistent(bot_id, auto_restart)
        
        if success:
            return jsonify({'success': True, 'message': f'Bot {bot_id} restarted'})
        else:
            return jsonify({'error': message}), 400
    except Exception as e:
        logger.error(f"Error in restart_bot: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/toggle_auto_restart', methods=['POST'])
def toggle_auto_restart(bot_id):
    """Toggle auto-restart for a bot"""
    try:
        bot_state = state_manager.get_bot_state(bot_id)
        if not bot_state:
            return jsonify({'error': 'Bot not found'}), 404
        
        current = bot_state.get('auto_restart', True)
        new_value = not current
        
        state_manager.update_bot_state(bot_id, bot_state.get('status', 'stopped'), auto_restart=new_value)
        
        return jsonify({
            'success': True,
            'message': f'Auto-restart set to {new_value} for bot {bot_id}',
            'auto_restart': new_value
        })
    except Exception as e:
        logger.error(f"Error in toggle_auto_restart: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/logs')
def get_logs(bot_id):
    """Get bot logs"""
    try:
        log_path = get_absolute_path(app.config['LOGS_FOLDER']) / f"{bot_id}.log"
        if not log_path.exists():
            return jsonify({'logs': [], 'status': 'no_logs'})
        
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                logs = f.read().split('\n')[-100:]
        except:
            logs = []
        
        bot_state = state_manager.get_bot_state(bot_id)
        status = 'running' if bot_id in running_bots else (bot_state.get('status', 'stopped') if bot_state else 'stopped')
        
        return jsonify({
            'logs': logs,
            'status': status,
            'bot_id': bot_id,
            'auto_restart': bot_state.get('auto_restart', False) if bot_state else False
        })
    except Exception as e:
        logger.error(f"Error in get_logs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/files')
def list_bot_files(bot_id):
    """List bot files"""
    try:
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        if not bot_path.exists():
            return jsonify({'error': 'Bot not found'}), 404
        
        files = []
        for file in bot_path.iterdir():
            if file.is_file():
                files.append({
                    'name': file.name,
                    'size': file.stat().st_size,
                    'is_python': file.suffix == '.py',
                    'extension': file.suffix[1:] if file.suffix else 'txt',
                    'modified': datetime.fromtimestamp(file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        return jsonify({'files': files})
    except Exception as e:
        logger.error(f"Error in list_bot_files: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/view/<filename>')
def view_bot_file(bot_id, filename):
    """View bot file content"""
    try:
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        file_path = bot_path / secure_filename(filename)
        
        if not file_path.exists() or not file_path.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        return jsonify({
            'filename': filename,
            'content': content,
            'size': file_path.stat().st_size
        })
    except Exception as e:
        logger.error(f"Error in view_bot_file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/edit/<filename>', methods=['GET', 'POST'])
def edit_bot_file(bot_id, filename):
    """Edit bot file content"""
    try:
        if request.method == 'GET':
            # Return the edit page
            bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
            if not bot_path.exists():
                return "Bot not found", 404
            return render_template('edit_file.html', bot_id=bot_id, filename=filename)
        
        elif request.method == 'POST':
            # Save file content
            data = request.get_json()
            if not data or 'content' not in data:
                return jsonify({'error': 'No content provided'}), 400
            
            bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
            file_path = bot_path / secure_filename(filename)
            
            if not file_path.exists():
                return jsonify({'error': 'File not found'}), 404
            
            # Backup the original file
            backup_dir = bot_path / '.backups'
            backup_dir.mkdir(exist_ok=True, parents=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = backup_dir / f"{filename}.{timestamp}.bak"
            
            try:
                shutil.copy2(file_path, backup_path)
            except Exception as e:
                logger.warning(f"Could not create backup: {e}")
            
            # Write the new content
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(data['content'])
            
            # Update state
            state_manager.update_bot_state(
                bot_id, 
                state_manager.get_bot_state(bot_id).get('status', 'stopped'),
                last_edited=datetime.now().isoformat(),
                edited_file=filename
            )
            
            return jsonify({
                'success': True,
                'message': f'File {filename} saved successfully'
            })
    
    except Exception as e:
        logger.error(f"Error in edit_bot_file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/create', methods=['POST'])
def create_file(bot_id):
    """Create a new file in bot directory"""
    try:
        data = request.get_json()
        if not data or 'filename' not in data:
            return jsonify({'error': 'No filename provided'}), 400
        
        filename = secure_filename(data['filename'])
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        if not bot_path.exists():
            return jsonify({'error': 'Bot not found'}), 404
        
        file_path = bot_path / filename
        
        # Check if file already exists
        if file_path.exists():
            return jsonify({'error': f'File {filename} already exists'}), 400
        
        # Create the file with initial content
        initial_content = data.get('content', '')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        
        return jsonify({
            'success': True,
            'message': f'File {filename} created successfully',
            'filename': filename,
            'size': file_path.stat().st_size
        })
    except Exception as e:
        logger.error(f"Error in create_file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/delete_file/<filename>', methods=['POST'])
def delete_bot_file(bot_id, filename):
    """Delete a file from bot directory"""
    try:
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        file_path = bot_path / secure_filename(filename)
        
        if not file_path.exists() or not file_path.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        # Create a backup before deleting
        backup_dir = bot_path / '.backups'
        backup_dir.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f"{filename}.{timestamp}.bak"
        
        try:
            shutil.copy2(file_path, backup_path)
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")
        
        # Delete the file
        file_path.unlink()
        
        return jsonify({
            'success': True,
            'message': f'File {filename} deleted successfully'
        })
    except Exception as e:
        logger.error(f"Error in delete_bot_file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/execute', methods=['POST'])
def execute_command(bot_id):
    """Execute a command in bot directory"""
    try:
        data = request.get_json()
        if not data or 'command' not in data:
            return jsonify({'error': 'No command provided'}), 400
        
        command = data['command']
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        
        if not bot_path.exists():
            return jsonify({'error': 'Bot not found'}), 404
        
        # Execute the command
        if sys.platform == 'win32':
            # Use cmd on Windows
            full_command = f'cd /d "{bot_path}" && {command}'
            shell = True
        else:
            # Use bash on Linux/Mac
            full_command = f'cd "{bot_path}" && {command}'
            shell = True
        
        result = subprocess.run(
            full_command,
            shell=shell,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=30
        )
        
        return jsonify({
            'success': True,
            'command': command,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out after 30 seconds'}), 408
    except Exception as e:
        logger.error(f"Error in execute_command: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/delete', methods=['POST'])
def delete_bot(bot_id):
    """Delete a bot"""
    try:
        if bot_id in running_bots:
            return jsonify({'error': 'Stop bot before deleting'}), 400
        
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        log_path = get_absolute_path(app.config['LOGS_FOLDER']) / f"{bot_id}.log"
        
        if bot_path.exists():
            shutil.rmtree(bot_path, ignore_errors=True)
        
        if log_path.exists():
            try:
                log_path.unlink()
            except:
                pass
        
        # Remove from state
        state_manager.remove_bot_state(bot_id)
        
        return jsonify({'success': True, 'message': f'Bot {bot_id} deleted'})
    except Exception as e:
        logger.error(f"Error in delete_bot: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/bot/<bot_id>/state')
def get_bot_state(bot_id):
    """Get detailed bot state"""
    try:
        bot_state = state_manager.get_bot_state(bot_id)
        if not bot_state:
            return jsonify({'error': 'Bot not found'}), 404
        
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        bot_state['exists'] = bot_path.exists()
        bot_state['is_running'] = bot_id in running_bots
        
        if bot_id in running_bots:
            bot_info = running_bots[bot_id]
            bot_state['process_info'] = {
                'start_time': bot_info['start_time'].isoformat(),
                'log_path': bot_info['log_path']
            }
        
        return jsonify(bot_state)
    except Exception as e:
        logger.error(f"Error in get_bot_state: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/system/state')
def get_system_state():
    """Get complete system state"""
    try:
        return jsonify({
            'server': {
                'start_time': state_manager.state.get('server_start_time'),
                'last_updated': state_manager.state.get('last_updated'),
                'running_bots_count': len(running_bots),
                'total_bots_count': len(state_manager.get_all_bots_state())
            },
            'config': state_manager.config,
            'bots': state_manager.get_all_bots_state()
        })
    except Exception as e:
        logger.error(f"Error in get_system_state: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/system/config', methods=['GET', 'POST'])
def system_config():
    """Get or update system configuration"""
    try:
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            for key, value in data.items():
                state_manager.set_config(key, value)
            
            return jsonify({
                'success': True,
                'message': 'Configuration updated',
                'config': state_manager.config
            })
        
        return jsonify(state_manager.config)
    except Exception as e:
        logger.error(f"Error in system_config: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/system/backup', methods=['POST'])
def backup_system_state():
    """Create a backup of system state"""
    try:
        backup_dir = Path('backups')
        backup_dir.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f'backup_{timestamp}.json'
        
        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'state': state_manager.state,
            'config': state_manager.config,
            'running_bots': list(running_bots.keys())
        }
        
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, default=str)
        
        return jsonify({
            'success': True,
            'message': f'Backup created: {backup_file}',
            'backup_file': str(backup_file)
        })
    except Exception as e:
        logger.error(f"Error in backup_system_state: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/system/restart_all', methods=['POST'])
def restart_all_bots():
    """Restart all bots that should be running"""
    try:
        data = request.get_json() or {}
        force = data.get('force', False)
        
        # Get list of bots to restart
        bots_to_restart = []
        for bot_id in list(running_bots.keys()):
            stop_bot_persistent(bot_id)
            bots_to_restart.append(bot_id)
        
        # Wait a moment
        time.sleep(1)
        
        # Start bots based on state
        restarted = 0
        for bot_id in bots_to_restart:
            bot_state = state_manager.get_bot_state(bot_id)
            if force or bot_state.get('auto_restart', False):
                start_bot_persistent(bot_id, bot_state.get('auto_restart', False))
                restarted += 1
        
        return jsonify({
            'success': True,
            'message': f'Restarted {restarted} bots',
            'restarted_count': restarted
        })
    except Exception as e:
        logger.error(f"Error in restart_all_bots: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'running_bots': len(running_bots),
        'python': sys.version,
        'platform': sys.platform,
        'state_file': str(state_manager.state_file),
        'config': {
            'auto_start': state_manager.get_config('auto_start', True),
            'auto_restart_on_crash': state_manager.get_config('auto_restart_on_crash', False)
        }
    })

@app.route('/bot/<bot_id>/manage')
def manage_bot(bot_id):
    """Bot management page"""
    try:
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        if not bot_path.exists():
            return "Bot not found", 404
        
        bot_state = state_manager.get_bot_state(bot_id)
        
        return render_template('manage_bot.html', 
                              bot_id=bot_id, 
                              bot_state=bot_state,
                              is_running=bot_id in running_bots)
    except Exception as e:
        logger.error(f"Error in manage_bot: {e}")
        return f"Error: {e}", 500

# ==================== TEMPLATES ====================

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found', 'message': str(e)}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large', 'message': str(e)}), 413

# ==================== MAIN ====================

def save_state_on_exit():
    """Save state when server exits"""
    logger.info("Saving bot state before exit...")
    
    # Update state for all running bots
    for bot_id in running_bots:
        state_manager.update_bot_state(bot_id, 'stopped', stopped_by='server_shutdown')
    
    # Save final state
    state_manager.save_state()
    logger.info("Bot state saved successfully")

# Register exit handler
atexit.register(save_state_on_exit)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    print("=" * 60)
    print("🚀 Flask Bot Hosting Platform with Persistent State")
    print(f"📁 Bots folder: {get_absolute_path(app.config['BOTS_FOLDER'])}")
    print(f"📁 State file: {state_manager.state_file}")
    print(f"🐍 Python: {sys.version.split()[0]}")
    print(f"🌐 Platform: {sys.platform}")
    print("=" * 60)
    
    # Auto-start bots if configured
    if state_manager.get_config('auto_start', True):
        print("🔄 Auto-starting bots from saved state...")
        auto_start_bots()
    else:
        print("⏸️ Auto-start disabled in configuration")
    
    print(f"✅ Server starting on http://{host}:{port}")
    
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\n⚠️ Server stopping...")
        save_state_on_exit()
        print("👋 Goodbye!")
    except Exception as e:
        print(f"❌ Server error: {e}")
        save_state_on_exit()
