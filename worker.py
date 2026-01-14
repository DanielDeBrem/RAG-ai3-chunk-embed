#!/usr/bin/env python3
"""
AI-3 DataFactory Worker

Processes jobs from the persistent job queue.

Usage:
    python worker.py [--poll-interval 1.0]
"""
import os
import sys
import argparse
import logging
import signal

# Initialize database before importing job handlers
from models import init_db
from job_queue import run_worker

# Import app_v1 to register job handlers
import app_v1

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_requested = True


def main():
    """Main worker entry point."""
    parser = argparse.ArgumentParser(description='AI-3 DataFactory Worker')
    parser.add_argument(
        '--poll-interval',
        type=float,
        default=1.0,
        help='Seconds to wait between polling for jobs (default: 1.0)'
    )
    parser.add_argument(
        '--database-url',
        type=str,
        default=os.getenv('DATABASE_URL', 'sqlite:///./ai3_rag.db'),
        help='Database URL (default: sqlite:///./ai3_rag.db)'
    )
    
    args = parser.parse_args()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize database
    logger.info(f"Initializing database: {args.database_url}")
    init_db(args.database_url)
    
    # Start worker loop
    logger.info(f"Starting worker (poll_interval={args.poll_interval}s)")
    logger.info("Press Ctrl+C to stop")
    
    try:
        run_worker(poll_interval=args.poll_interval)
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("Worker shutdown complete")


if __name__ == '__main__':
    main()
