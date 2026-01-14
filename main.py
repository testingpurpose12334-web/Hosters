# app.py - Fixed Flask Bot Hosting Platform with encoding fixes
import os
import sys
import time
import json
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

# Configuration
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production'),
    UPLOAD_FOLDER='uploads',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    ALLOWED_EXTENSIONS={'py', 'txt', 'json', 'env', 'yaml', 'yml', 'cfg', 'ini'},
    BOTS_FOLDER='bots',
    LOGS_FOLDER='logs'
)

# Create necessary directories
for folder in [app.config['UPLOAD_FOLDER'], app.config['BOTS_FOLDER'], app.config['LOGS_FOLDER']]:
    Path(folder).mkdir(exist_ok=True)

# Store running bot processes
running_bots = {}

def get_python_executable():
    """Get the correct Python executable path"""
    # On Windows, use python.exe instead of pythonw.exe for console output
    if sys.platform == 'win32':
        # Try to find python.exe in the same directory as pythonw.exe
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

def run_bot_with_encoding_fix(bot_id, bot_path):
    """Run bot with proper encoding handling"""
    log_path = get_absolute_path(app.config['LOGS_FOLDER']) / f"{bot_id}.log"
    python_executable = get_python_executable()
    
    log_path.parent.mkdir(exist_ok=True)
    
    # Create an environment with UTF-8 encoding
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    
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
                    log_file.write(f"Error: {result.stderr}\n")
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
                bufsize=1
            )
            
            running_bots[bot_id] = {
                'process': process,
                'start_time': datetime.now(),
                'log_path': str(log_path)
            }
            
            # Read output in real-time
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_file.write(f"[{timestamp}] {output}")
                    log_file.flush()
            
            return_code = process.poll()
            log_file.write(f"[{datetime.now()}] Bot process ended with code: {return_code}\n")
            
        except Exception as e:
            log_file.write(f"[{datetime.now()}] Error running bot: {str(e)}\n")
        finally:
            if bot_id in running_bots:
                del running_bots[bot_id]

@app.route('/')
def index():
    """Main dashboard"""
    bots = []
    bots_folder = get_absolute_path(app.config['BOTS_FOLDER'])
    
    if bots_folder.exists():
        for bot_dir in bots_folder.iterdir():
            if bot_dir.is_dir():
                bot_info = {
                    'id': bot_dir.name,
                    'name': bot_dir.name,
                    'status': 'running' if bot_dir.name in running_bots else 'stopped',
                    'created_at': datetime.fromtimestamp(bot_dir.stat().st_ctime).strftime('%Y-%m-%d %H:%M'),
                    'files': [f.name for f in bot_dir.iterdir() if f.is_file()],
                    'has_py': any(f.suffix == '.py' for f in bot_dir.iterdir() if f.is_file())
                }
                bots.append(bot_info)
    
    return render_template('index.html', bots=bots, python_executable=get_python_executable())

@app.route('/upload', methods=['GET', 'POST'])
def upload_bot():
    """Upload bot files"""
    if request.method == 'POST':
        if 'files[]' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files[]')
        bot_name = request.form.get('bot_name', '').strip()
        
        if not bot_name:
            bot_name = f"bot_{int(time.time())}"
        
        bot_id = secure_filename(bot_name.replace(' ', '_'))
        bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
        bot_path.mkdir(exist_ok=True)
        
        uploaded_files = []
        for file in files:
            if file and (allowed_file(file.filename) or file.filename == 'requirements.txt'):
                filename = secure_filename(file.filename)
                file_path = bot_path / filename
                file.save(file_path)
                uploaded_files.append(filename)
        
        return jsonify({
            'success': True,
            'bot_id': bot_id,
            'message': f'Uploaded {len(uploaded_files)} files',
            'files': uploaded_files
        })
    
    return render_template('upload.html')

@app.route('/bot/<bot_id>/start', methods=['POST'])
def start_bot(bot_id):
    """Start a bot"""
    if bot_id in running_bots:
        return jsonify({'error': 'Bot is already running'}), 400
    
    bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
    if not bot_path.exists():
        return jsonify({'error': 'Bot not found'}), 404
    
    # Check if there are Python files
    python_files = [f for f in bot_path.iterdir() if f.is_file() and f.suffix == '.py']
    if not python_files:
        return jsonify({'error': 'No Python files found in bot directory'}), 400
    
    # Start bot in background
    bot_thread = threading.Thread(
        target=run_bot_with_encoding_fix,
        args=(bot_id, bot_path),
        daemon=True
    )
    bot_thread.start()
    
    # Give it a moment to start
    time.sleep(0.5)
    
    return jsonify({
        'success': True,
        'message': f'Bot {bot_id} started',
        'python_executable': get_python_executable()
    })

@app.route('/bot/<bot_id>/stop', methods=['POST'])
def stop_bot(bot_id):
    """Stop a running bot"""
    if bot_id not in running_bots:
        return jsonify({'error': 'Bot is not running'}), 400
    
    bot_info = running_bots[bot_id]
    process = bot_info['process']
    
    try:
        process.terminate()
        process.wait(timeout=5)
    except:
        try:
            process.kill()
            process.wait()
        except:
            pass
    
    if bot_id in running_bots:
        del running_bots[bot_id]
    
    return jsonify({'success': True, 'message': f'Bot {bot_id} stopped'})

@app.route('/bot/<bot_id>/logs')
def get_logs(bot_id):
    """Get bot logs"""
    log_path = get_absolute_path(app.config['LOGS_FOLDER']) / f"{bot_id}.log"
    if not log_path.exists():
        return jsonify({'logs': [], 'status': 'no_logs'})
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            logs = f.read().split('\n')[-100:]
    except:
        logs = []
    
    status = 'running' if bot_id in running_bots else 'stopped'
    
    return jsonify({
        'logs': logs,
        'status': status,
        'bot_id': bot_id
    })

@app.route('/bot/<bot_id>/files')
def list_bot_files(bot_id):
    """List bot files"""
    bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
    if not bot_path.exists():
        return jsonify({'error': 'Bot not found'}), 404
    
    files = []
    for file in bot_path.iterdir():
        if file.is_file():
            files.append({
                'name': file.name,
                'size': file.stat().st_size,
                'is_python': file.suffix == '.py'
            })
    
    return jsonify({'files': files})

@app.route('/bot/<bot_id>/view/<filename>')
def view_bot_file(bot_id, filename):
    """View bot file content"""
    bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
    file_path = bot_path / secure_filename(filename)
    
    if not file_path.exists() or not file_path.is_file():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return jsonify({
            'filename': filename,
            'content': content,
            'size': file_path.stat().st_size
        })
    except Exception as e:
        return jsonify({'error': f'Cannot read file: {str(e)}'}), 500

@app.route('/bot/<bot_id>/delete', methods=['POST'])
def delete_bot(bot_id):
    """Delete a bot"""
    if bot_id in running_bots:
        return jsonify({'error': 'Stop bot before deleting'}), 400
    
    bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
    log_path = get_absolute_path(app.config['LOGS_FOLDER']) / f"{bot_id}.log"
    
    if bot_path.exists():
        import shutil
        shutil.rmtree(bot_path)
    
    if log_path.exists():
        try:
            log_path.unlink()
        except:
            pass
    
    return jsonify({'success': True, 'message': f'Bot {bot_id} deleted'})

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'running_bots': len(running_bots),
        'python': sys.version,
        'platform': sys.platform,
        'python_executable': get_python_executable()
    })

@app.route('/bot/<bot_id>/manage')
def manage_bot(bot_id):
    bot_path = get_absolute_path(app.config['BOTS_FOLDER']) / bot_id
    if not bot_path.exists():
        return "Bot not found", 404
    
    # Check if bot has Python files
    python_files = [f.name for f in bot_path.iterdir() if f.is_file() and f.suffix == '.py']
    
    return render_template('manage_bot.html', 
                          bot_id=bot_id, 
                          has_python_files=len(python_files) > 0,
                          python_files=python_files)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    print("🚀 Flask Bot Hosting Platform")
    print(f"📁 Bots folder: {get_absolute_path(app.config['BOTS_FOLDER'])}")
    print(f"🐍 Python executable: {get_python_executable()}")
    print(f"🌐 Platform: {sys.platform}")
    print(f"🔤 Encoding: {sys.getdefaultencoding()}")
    
    app.run(host=host, port=port, debug=debug)
