# Generated manually for adding session_id field
# pylint: disable=invalid-name,missing-module-docstring
"""Migration adding session_id field to Chat model."""
from django.db import migrations, models


class Migration(migrations.Migration):
    """Migration adding session_id field to Chat model."""

    dependencies = [
        ('chat', '0006_alter_chat_id_alter_chatmessage_id_alter_document_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='session_id',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Session ID starting from 1 for each user'
            ),
        ),
        migrations.AlterUniqueTogether(
            name='chat',
            unique_together={('chat_id', 'user'), ('session_id', 'user')},
        ),
    ]
