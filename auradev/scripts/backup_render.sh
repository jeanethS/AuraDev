#!/bin/bash
# Backup script for Render deployment
# Run this from your local machine via Render Shell

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/tmp/backups"
DB_PATH="/opt/render/project/data/auradev.db"

mkdir -p $BACKUP_DIR

# Create backup
sqlite3 $DB_PATH ".backup '$BACKUP_DIR/auradev_$DATE.db'"

# Download to local (you'll need to scp this)
echo "Backup created: $BACKUP_DIR/auradev_$DATE.db"
echo "Download via Render Shell or mount the disk locally"

# Keep only last 7 backups
ls -t $BACKUP_DIR/auradev_*.db | tail -n +8 | xargs rm -f

echo "Backup complete!"
