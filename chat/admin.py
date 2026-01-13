"""Django admin configuration for Chat model."""
from django import forms
from django.contrib import admin
from .models import Chat

class ChatAdminForm(forms.ModelForm):
    """Custom form for Chat admin with readable conversation format"""
    conversation_history_text = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 25,
            'cols': 100,
            'style': (
                'font-family: Arial, sans-serif; font-size: 14px; '
                'line-height: 1.6; width: 100%; padding: 10px;'
            ),
            'class': 'vLargeTextField',
            'placeholder': (
                'User: Your message here\nAssistant: AI response here\n\n'
                'User: Another message\nAssistant: Another response'
            )
        }),
        required=False,
        label='Conversation History',
        help_text=(
            'Enter conversation in readable format. Each message on a new '
            'line starting with "User:" or "Assistant:"'
        )
    )

    class Meta:
        """Meta options for ChatAdminForm."""
        model = Chat
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Convert JSON to readable format
            history = self.instance.get_conversation_history()
            if history:
                readable_text = self._json_to_readable(history)
                self.initial['conversation_history_text'] = readable_text
            else:
                self.initial['conversation_history_text'] = ''

    def _json_to_readable(self, history):
        """Convert JSON conversation history to readable text format"""
        lines = []
        for msg in history:
            role = msg.get('role', 'unknown').capitalize()
            content = msg.get('content', '')
            lines.append(f"{role}: {content}")
        return '\n\n'.join(lines)

    def _readable_to_json(self, text):
        """Convert readable text format to JSON"""
        if not text or not text.strip():
            return []

        messages = []
        lines = text.split('\n')
        current_role = None
        current_content = []

        for line in lines:
            line = line.strip()
            if not line:
                if current_role and current_content:
                    messages.append({
                        'role': current_role.lower(),
                        'content': '\n'.join(current_content).strip()
                    })
                    current_content = []
                continue

            # Check if line starts with "User:" or "Assistant:"
            if line.lower().startswith('user:'):
                if current_role and current_content:
                    messages.append({
                        'role': current_role.lower(),
                        'content': '\n'.join(current_content).strip()
                    })
                current_role = 'user'
                content = line[5:].strip()  # Remove "User:" prefix
                current_content = [content] if content else []
            elif line.lower().startswith('assistant:'):
                if current_role and current_content:
                    messages.append({
                        'role': current_role.lower(),
                        'content': '\n'.join(current_content).strip()
                    })
                current_role = 'assistant'
                content = line[10:].strip()  # Remove "Assistant:" prefix
                current_content = [content] if content else []
            else:
                # Continuation of previous message
                if current_role:
                    current_content.append(line)

        # Add last message
        if current_role and current_content:
            messages.append({
                'role': current_role.lower(),
                'content': '\n'.join(current_content).strip()
            })

        return messages

    def clean_conversation_history_text(self):
        """Convert readable format to JSON"""
        text = self.cleaned_data.get('conversation_history_text', '')
        return self._readable_to_json(text)

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Get the converted JSON from the readable text
        readable_text = self.cleaned_data.get('conversation_history_text', '')
        instance.conversation_history = self._readable_to_json(readable_text)
        if commit:
            instance.save()
        return instance

@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    """Admin interface for Chat model."""
    form = ChatAdminForm
    list_display = (
        'session_id', 'user', 'title', 'created_at', 'updated_at',
        'conversation_length'
    )
    list_filter = ('created_at', 'updated_at', 'user')
    search_fields = ('session_id', 'chat_id', 'title', 'user__username')
    readonly_fields = ('session_id', 'chat_id', 'created_at', 'updated_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('session_id', 'chat_id', 'user', 'title')
        }),
        ('Conversation History', {
            'fields': ('conversation_history_text',),
            'classes': ('wide',),
            'description': (
                'Edit conversation in readable format. Start each message '
                'with "User:" or "Assistant:" followed by the message content.'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def conversation_length(self, obj):
        """Display number of messages in conversation history"""
        history = obj.get_conversation_history()
        return len(history) if history else 0
    conversation_length.short_description = 'Messages'
