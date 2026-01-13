"""Views for chat application."""
import json
import os
import traceback
import uuid
from dotenv import load_dotenv
from groq import Groq
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .document_processor import extract_text_from_file, get_file_type
from .models import Chat, ChatMessage, Document

load_dotenv()

# Initialize Groq client (will be created when needed)
def get_groq_client():
    """Initialize and return a Groq API client."""
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        raise ValueError("GROQ_API_KEY not found in environment variables")
    return Groq(api_key=api_key)

def login_view(request):
    """Handle user login"""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            messages.error(request, 'Please provide both username and password.')
            return render(request, 'chat/login.html')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('index')
        messages.error(request, 'Invalid username or password.')

    return render(request, 'chat/login.html')

def signup_view(request):  # pylint: disable=too-many-branches
    """Handle user registration"""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        # Validation
        errors = []

        if not username:
            errors.append('Username is required.')
        elif len(username) < 3:
            errors.append('Username must be at least 3 characters long.')
        elif User.objects.filter(username=username).exists():
            errors.append('Username already exists.')

        if not password:
            errors.append('Password is required.')
        elif len(password) < 8:
            errors.append('Password must be at least 8 characters long.')
        elif not any(char.isdigit() for char in password):
            errors.append('Password must contain at least one number.')
        elif not any(char.isalpha() for char in password):
            errors.append('Password must contain at least one letter.')

        if password != password_confirm:
            errors.append('Passwords do not match.')

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'chat/signup.html')

        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                password=password
            )
            login(request, user)
            messages.success(request, 'Account created successfully!')
            return redirect('index')
        except Exception as e:
            messages.error(request, f'Error creating account: {str(e)}')

    return render(request, 'chat/signup.html')

def logout_view(request):
    """Handle user logout - clear session and redirect to login"""
    # Clear all session data including active documents
    request.session.flush()
    # Logout the user
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')

@login_required
def index(request):
    """Render the main chat interface"""
    # Ensure user is authenticated
    if not request.user.is_authenticated:
        return redirect('login')

    # Add cache-control headers to prevent caching after logout
    response = render(request, 'chat/index.html')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def chat(request):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Handle chat messages and return AI responses.
    Automatically injects active document text from session if available."""
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()

        if not user_message:
            return JsonResponse({'error': 'Message cannot be empty'}, status=400)

        # Get Groq client
        try:
            groq_client = get_groq_client()
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=500)

        # Get conversation history if available
        conversation_history = data.get('history', [])

        # AUTOMATIC DOCUMENT CONTEXT INJECTION
        # Get chat_id to scope documents per chat
        chat_id = data.get('chat_id')

        # Check if there are active documents for this specific chat
        # (supports multiple documents)
        chat_documents = request.session.get('chat_documents', {})
        # Dict: {chat_id: [documents]}
        active_documents = (
            chat_documents.get(chat_id, []) if chat_id else []
        )  # List of dicts: {id, filename, text}

        # Prepare messages for Groq API
        messages = []  # pylint: disable=redefined-outer-name

        # Add system message - enhanced if documents are active
        if active_documents:
            doc_count = len(active_documents)
            if doc_count == 1:
                system_content = (
                    "You are a helpful AI assistant with access to a "
                    "document that the user has uploaded.\n"
                    "You can see the full content of the document and "
                    "should answer questions based on it.\n"
                    "When the user asks to \"summarize\" or \"summarize "
                    "the attached pdf\" or similar, automatically provide "
                    "a summary of the document.\n"
                    "Provide brief, concise answers that cover all "
                    "important information comprehensively.\n"
                    "Be succinct but ensure you include all key points.\n"
                    "When answering, use information from the document "
                    "when relevant.\n"
                    "Never say you can't access attachments or ask the "
                    "user to paste text - you already have the document "
                    "content."
                )
            else:
                system_content = (
                    f"You are a helpful AI assistant with access to "
                    f"{doc_count} documents that the user has uploaded.\n"
                    f"You can see the full content of all documents and "
                    f"should answer questions based on them.\n"
                    f"The documents are numbered: Document 1 (first "
                    f"document), Document 2 (second document), etc.\n"
                    f"When the user asks to \"summarize the first document\" "
                    f"or \"summarize document 1\", summarize Document 1.\n"
                    f"When the user asks to \"summarize the second document\" "
                    f"or \"summarize document 2\", summarize Document 2.\n"
                    f"When the user asks to \"summarize\" without "
                    f"specifying, summarize all documents.\n"
                    f"Provide brief, concise answers that cover all "
                    f"important information comprehensively.\n"
                    f"Be succinct but ensure you include all key points.\n"
                    f"When answering, use information from the relevant "
                    f"document(s) when relevant.\n"
                    f"Never say you can't access attachments or ask the "
                    f"user to paste text - you already have the document "
                    f"content."
                )
        else:
            system_content = (
                "You are a helpful AI assistant. Provide brief, concise "
                "answers that cover all important information "
                "comprehensively. Be succinct but ensure you include all "
                "key points. Keep responses focused and to the point while "
                "maintaining completeness. Use clear, direct language and "
                "avoid unnecessary elaboration."
            )

        messages.append({
            "role": "system",
            "content": system_content
        })

        # Add document context as hidden context if available
        if active_documents:
            # Build context from all documents
            doc_contexts = []
            for idx, doc in enumerate(active_documents, 1):
                doc_text = doc.get('text', '')
                doc_filename = doc.get('filename', f'Document {idx}')
                # Truncate each document if needed
                # (max 15000 chars per document for context)
                if len(doc_text) > 15000:
                    doc_text = (
                        doc_text[:15000] +
                        "\n\n[Document content continues but was "
                        "truncated...]"
                    )
                doc_contexts.append(
                    f"Document {idx} ('{doc_filename}'):\n{doc_text}"
                )

            all_docs_text = "\n\n---\n\n".join(doc_contexts)

            # Inject document context before user message
            messages.append({
                "role": "user",
                "content": (
                    f"[Document context from uploaded files:\n"
                    f"{all_docs_text}\n]\n\n"
                    f"Now answer the user's question based on the above "
                    f"document content:"
                )
            })

        # Add conversation history
        for msg in conversation_history:
            # Skip system messages from history to avoid duplication
            if msg.get('role') != 'system':
                messages.append({
                    "role": msg.get('role', 'user'),
                    "content": msg.get('content', '')
                })

        # Add current user message
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Call Groq API
        # Get model from environment variable or use default
        # Available models: llama-3.1-8b-instant, llama-3.1-70b-versatile, mixtral-8x7b-32768
        model = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')

        chat_completion = groq_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=800,  # Reduced to encourage more concise responses
        )

        # Extract response
        ai_response = chat_completion.choices[0].message.content

        # AUTOMATICALLY SAVE CONVERSATION TO DATABASE
        # Get or create chat for this conversation
        if not chat_id:
            # Generate a chat_id if not provided
            chat_id = str(uuid.uuid4())

        try:
            # pylint: disable=no-member,redefined-outer-name
            chat = Chat.objects.get(chat_id=chat_id, user=request.user)
        except Chat.DoesNotExist:  # pylint: disable=no-member
            # Create new chat with title from first user message
            title = user_message[:50] if len(user_message) > 50 else user_message
            if not title:
                title = 'New Chat'
            # Get next global session_id
            # (starting from 1, sequential across all users)
            session_id = Chat.get_next_session_id()
            # pylint: disable=no-member
            chat = Chat.objects.create(
                chat_id=chat_id,
                session_id=session_id,
                user=request.user,
                title=title
            )

        # Save user message to database
        # pylint: disable=no-member
        ChatMessage.objects.create(
            chat=chat,  # pylint: disable=redefined-outer-name
            role='user',
            content=user_message
        )

        # Save AI response to database
        ChatMessage.objects.create(
            chat=chat,  # pylint: disable=redefined-outer-name
            role='assistant',
            content=ai_response
        )

        # Update conversation history in Chat model
        chat.add_to_history('user', user_message)
        chat.add_to_history('assistant', ai_response)

        # Update chat title if it's still "New Chat" and we have a better title
        if chat.title == 'New Chat' and user_message:
            title = user_message[:50] if len(user_message) > 50 else user_message
            chat.title = title
            chat.save()

        return JsonResponse({
            'response': ai_response,
            'status': 'success',
            'chat_id': chat_id  # Return chat_id so frontend can use it
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error in chat: {traceback.format_exc()}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["GET"])
def get_chats(request):
    """Get all chats for the current user"""
    try:
        # pylint: disable=no-member
        chats = Chat.objects.filter(user=request.user)
        chats_data = []
        for chat in chats:  # pylint: disable=redefined-outer-name
            chats_data.append({
                'id': chat.chat_id,
                'title': chat.title,
                'updatedAt': int(chat.updated_at.timestamp() * 1000)
            })
        return JsonResponse({'chats': chats_data, 'status': 'success'})
    except Exception as e:  # pylint: disable=broad-exception-caught
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["GET"])
def get_chat(request, chat_id):
    """Get a specific chat with all messages"""
    try:
        # pylint: disable=no-member,redefined-outer-name
        chat = get_object_or_404(Chat, chat_id=chat_id, user=request.user)
        messages = chat.messages.all()  # pylint: disable=no-member,redefined-outer-name
        messages_data = []
        history_data = []

        for msg in messages:
            messages_data.append({
                'role': msg.role,
                'content': msg.content
            })
            history_data.append({
                'role': msg.role,
                'content': msg.content
            })

        return JsonResponse({
            'chat': {
                'id': chat.chat_id,
                'title': chat.title,
                'messages': messages_data,
                'history': history_data
            },
            'status': 'success'
        })
    except Chat.DoesNotExist:  # pylint: disable=no-member
        return JsonResponse({'error': 'Chat not found'}, status=404)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error in get_chat: {traceback.format_exc()}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def save_chat(request, chat_id):
    """Save or update a chat"""
    try:
        data = json.loads(request.body)
        title = data.get('title', 'New Chat')
        messages_data = data.get('messages', [])
        # history_data is kept for potential future use
        _ = data.get('history', [])  # pylint: disable=unused-variable

        if not chat_id:
            return JsonResponse({'error': 'chat_id is required'}, status=400)

        # Get or create chat (user-specific)
        try:
            # pylint: disable=no-member,redefined-outer-name
            chat = Chat.objects.get(chat_id=chat_id, user=request.user)
            chat.title = title
            chat.save()
            # Delete existing messages
            chat.messages.all().delete()  # pylint: disable=no-member
        except Chat.DoesNotExist:  # pylint: disable=no-member
            # Get next global session_id
            # (starting from 1, sequential across all users)
            session_id = Chat.get_next_session_id()
            chat = Chat.objects.create(  # pylint: disable=redefined-outer-name
                chat_id=chat_id,
                session_id=session_id,
                user=request.user,
                title=title
            )

        # Create messages
        for msg_data in messages_data:
            # pylint: disable=no-member
            ChatMessage.objects.create(
                chat=chat,  # pylint: disable=redefined-outer-name
                role=msg_data.get('role', 'user'),
                content=msg_data.get('content', '')
            )

        return JsonResponse({
            'chat_id': chat.chat_id,
            'status': 'success'
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Log the full traceback for debugging
        print(f"Error in save_chat: {traceback.format_exc()}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_chat(request, chat_id):
    """Delete a chat"""
    try:
        # pylint: disable=no-member,redefined-outer-name
        chat = get_object_or_404(Chat, chat_id=chat_id, user=request.user)
        chat.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:  # pylint: disable=broad-exception-caught
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def upload_document(request):
    """Handle document upload and automatic text extraction.
    Stores extracted text in session per chat_id for automatic LLM context injection."""
    try:  # pylint: disable=too-many-locals
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)

        uploaded_file = request.FILES['file']

        # Get chat_id from request data (sent from frontend via FormData)
        chat_id = request.POST.get('chat_id', '')

        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if uploaded_file.size > max_size:
            return JsonResponse({'error': 'File size exceeds 10MB limit'}, status=400)

        # Process file in-memory (no file storage)
        file_type = get_file_type(uploaded_file.name)

        # AUTOMATIC TEXT EXTRACTION - happens immediately on upload (in-memory)
        extracted_text = extract_text_from_file(uploaded_file, file_type)

        # Save document metadata (no file storage)
        # pylint: disable=no-member
        document = Document.objects.create(
            user=request.user,
            filename=uploaded_file.name,
            file_type=file_type,
            file_size=uploaded_file.size,
            extracted_text=extracted_text
        )

        # Store extracted text in session memory per chat_id for automatic LLM injection
        # Support multiple documents (up to 2 like ChatGPT)
        if extracted_text and extracted_text.strip():
            # Truncate if too large
            # (max 50000 chars per document to avoid token limits)
            max_text_length = 50000
            if len(extracted_text) > max_text_length:
                extracted_text = (
                    extracted_text[:max_text_length] +
                    "\n\n[Document truncated for length...]"
                )

            # Get chat-specific documents dictionary
            chat_documents = request.session.get('chat_documents', {})

            # Get existing active documents for this chat (or empty list if new chat)
            if chat_id:
                active_documents = chat_documents.get(chat_id, [])
            else:
                active_documents = []

            # Remove this document if it already exists (to avoid duplicates)
            active_documents = [d for d in active_documents if d.get('id') != document.id]

            # Add new document
            active_documents.append({
                'id': document.id,
                'filename': document.filename,
                'text': extracted_text
            })

            # Keep only the 2 most recent documents (like ChatGPT)
            if len(active_documents) > 2:
                active_documents = active_documents[-2:]

            # Store documents per chat_id
            if chat_id:
                chat_documents[chat_id] = active_documents
            else:
                # If no chat_id provided, use a default key (backward compatibility)
                chat_documents['default'] = active_documents

            request.session['chat_documents'] = chat_documents
            text_length = len(extracted_text)
        else:
            # Don't add to session if no text extracted
            text_length = 0

        return JsonResponse({
            'status': 'success',
            'document_id': document.id,
            'filename': document.filename,
            'file_type': document.file_type,
            'file_size': document.file_size,
            'extracted_text_length': text_length,
            'message': 'Document uploaded and processed successfully'
        })

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error in upload_document: {traceback.format_exc()}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def summarize_document(request):  # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches,too-many-statements
    """Summarize a document using AI. Supports position-based requests (first, second, 1, 2)"""
    try:
        data = json.loads(request.body)
        document_id = data.get('document_id')
        position = data.get('position', '').lower().strip()  # 'first', 'second', '1', '2', or None

        # Get chat_id to scope documents per chat
        chat_id = data.get('chat_id')

        # Get active documents for this specific chat from session
        chat_documents = request.session.get('chat_documents', {})
        active_documents = chat_documents.get(chat_id, []) if chat_id else []

        # Determine which document to summarize
        document_to_summarize = None
        doc_index = None

        if position:
            # Position-based selection
            if position in ['first', '1']:
                doc_index = 0
            elif position in ['second', '2']:
                doc_index = 1
            else:
                return JsonResponse({
                    'error': (
                        f'Invalid position: {position}. '
                        f'Use "first", "second", "1", or "2"'
                    )
                }, status=400)

            if doc_index < len(active_documents):
                doc_data = active_documents[doc_index]
                document_id = doc_data.get('id')
                document_to_summarize = doc_data
            else:
                return JsonResponse({
                    'error': (
                        f'Document {position} not found. '
                        f'Only {len(active_documents)} document(s) available.'
                    )
                }, status=400)
        elif document_id:
            # Document ID-based selection
            # Find in active documents first
            for idx, doc_data in enumerate(active_documents):
                if doc_data.get('id') == document_id:
                    document_to_summarize = doc_data
                    doc_index = idx
                    break

            # If not in active documents, get from database
            if not document_to_summarize:
                document = get_object_or_404(Document, id=document_id, user=request.user)
                if not document.extracted_text:
                    return JsonResponse({'error': 'No text extracted from document'}, status=400)
                document_to_summarize = {
                    'id': document.id,
                    'filename': document.filename,
                    'text': document.extracted_text
                }
        else:
            # No position or ID specified - summarize all documents
            if not active_documents:
                return JsonResponse({'error': 'No documents available to summarize'}, status=400)

            # Summarize all documents
            summaries = []
            for idx, doc_data in enumerate(active_documents, 1):
                doc_text = doc_data.get('text', '')
                doc_filename = doc_data.get('filename', f'Document {idx}')

                if not doc_text or not doc_text.strip():
                    continue

                # Get Groq client
                try:
                    groq_client = get_groq_client()
                except ValueError as e:
                    return JsonResponse({'error': str(e)}, status=500)

                full_text_length = len(doc_text)
                prompt = (
                    f"Please provide a comprehensive summary of "
                    f"Document {idx} ('{doc_filename}').\n"
                    f"The document is {full_text_length} characters long. "
                    f"Here is the content:\n\n"
                    f"{doc_text}\n\n"
                    f"Please provide:\n"
                    f"1. A brief overview (2-3 sentences)\n"
                    f"2. Key points and main topics\n"
                    f"3. Important details or findings\n"
                    f"4. Any conclusions or recommendations if present\n\n"
                    f"Format your response in a clear, structured manner."
                )

                model = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')
                chat_completion = groq_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                        "You are a helpful assistant that provides clear, "
                        "comprehensive summaries of documents."
                    )
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.7,
                    max_tokens=1000
                )

                summary = chat_completion.choices[0].message.content
                summaries.append(f"**Document {idx}: {doc_filename}**\n\n{summary}")

            combined_summary = "\n\n---\n\n".join(summaries)
            return JsonResponse({
                'status': 'success',
                'filename': f"{len(active_documents)} document(s)",
                'summary': combined_summary
            })

        # Summarize single document
        if not document_to_summarize:
            return JsonResponse({'error': 'Document not found'}, status=404)

        doc_text = document_to_summarize.get('text', '')
        doc_filename = document_to_summarize.get('filename', 'Document')

        if not doc_text or not doc_text.strip():
            return JsonResponse({'error': 'No text extracted from document'}, status=400)

        # Get Groq client
        try:
            groq_client = get_groq_client()
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=500)

        # Prepare prompt for summarization
        full_text_length = len(doc_text)
        position_label = (
            f" (Document {doc_index + 1})" if doc_index is not None else ""
        )

        prompt = (
            f"Please provide a comprehensive summary of the following "
            f"document{position_label}.\n"
            f"The document is {full_text_length} characters long. "
            f"Here is the content:\n\n"
            f"{doc_text}\n\n"
            f"Please provide:\n"
            f"1. A brief overview (2-3 sentences)\n"
            f"2. Key points and main topics\n"
            f"3. Important details or findings\n"
            f"4. Any conclusions or recommendations if present\n\n"
            f"Format your response in a clear, structured manner."
        )

        model = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')

        chat_completion = groq_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that provides clear, "
                        "comprehensive summaries of documents."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=1500,
        )

        summary = chat_completion.choices[0].message.content

        # AUTOMATICALLY SAVE CONVERSATION TO DATABASE
        chat_id = data.get('chat_id')
        if chat_id:
            try:
                # pylint: disable=no-member,redefined-outer-name
                chat = Chat.objects.get(chat_id=chat_id, user=request.user)
            except Chat.DoesNotExist:  # pylint: disable=no-member
                # Create new chat with title from document filename
                title = f'Summary: {doc_filename}'
                # Get next session_id for this user (starting from 1)
                session_id = Chat.get_next_session_id()
                chat = Chat.objects.create(  # pylint: disable=redefined-outer-name
                    chat_id=chat_id,
                    session_id=session_id,
                    user=request.user,
                    title=title
                )

            # Save user message (document upload/summarize request)
            user_msg = f"Summarize: {doc_filename}"
            # pylint: disable=no-member
            ChatMessage.objects.create(
                chat=chat,  # pylint: disable=redefined-outer-name
                role='user',
                content=user_msg
            )

            # Save AI summary to database
            ChatMessage.objects.create(
                chat=chat,  # pylint: disable=redefined-outer-name
                role='assistant',
                content=summary
            )

            # Update conversation history in Chat model
            chat.add_to_history('user', user_msg)
            chat.add_to_history('assistant', summary)

        return JsonResponse({
            'status': 'success',
            'filename': doc_filename,
            'summary': summary,
            'chat_id': chat_id if chat_id else None
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def ask_document(request):  # pylint: disable=too-many-locals
    """Answer questions about a document using AI"""
    try:
        data = json.loads(request.body)
        document_id = data.get('document_id')
        question = data.get('question', '').strip()

        if not document_id:
            return JsonResponse({'error': 'document_id is required'}, status=400)

        if not question:
            return JsonResponse({'error': 'question is required'}, status=400)

        document = get_object_or_404(Document, id=document_id, user=request.user)

        if not document.extracted_text:
            return JsonResponse({'error': 'No text extracted from document'}, status=400)

        # Get Groq client
        try:
            groq_client = get_groq_client()
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=500)

        # Prepare prompt for Q&A
        # Limit document text to avoid token limits (keep it reasonable)
        doc_text = document.extracted_text
        if len(doc_text) > 8000:
            doc_text = doc_text[:8000] + "\n\n[Document truncated for length...]"

        prompt = (
            f"Based on the following document, please answer the user's "
            f"question.\n"
            f"If the answer is not in the document, please say so clearly.\n\n"
            f"Document content:\n{doc_text}\n\n"
            f"User's question: {question}\n\n"
            f"Please provide a clear, accurate answer based on the document "
            f"content."
        )

        model = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')

        chat_completion = groq_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that answers questions "
                        "based on provided documents. Be accurate and cite "
                        "specific information from the document when possible."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        answer = chat_completion.choices[0].message.content

        # AUTOMATICALLY SAVE CONVERSATION TO DATABASE
        chat_id = data.get('chat_id')
        if not chat_id:
            # Generate a chat_id if not provided
            chat_id = str(uuid.uuid4())

        try:
            # pylint: disable=no-member,redefined-outer-name
            chat = Chat.objects.get(chat_id=chat_id, user=request.user)
        except Chat.DoesNotExist:  # pylint: disable=no-member
            # Create new chat with title from question
            title = question[:50] if len(question) > 50 else question
            if not title:
                title = f'Document Q&A: {document.filename}'
            # Get next global session_id
            # (starting from 1, sequential across all users)
            session_id = Chat.get_next_session_id()
            chat = Chat.objects.create(  # pylint: disable=redefined-outer-name
                chat_id=chat_id,
                session_id=session_id,
                user=request.user,
                title=title
            )

            # Save user question to database
            # pylint: disable=no-member
            ChatMessage.objects.create(
                chat=chat,  # pylint: disable=redefined-outer-name
                role='user',
                content=question
            )

            # Save AI answer to database
            ChatMessage.objects.create(
                chat=chat,  # pylint: disable=redefined-outer-name
                role='assistant',
                content=answer
            )

            # Update conversation history in Chat model
            chat.add_to_history('user', question)
            chat.add_to_history('assistant', answer)

        return JsonResponse({
            'status': 'success',
            'answer': answer,
            'document_id': document.id,
            'filename': document.filename,
            'question': question,
            'chat_id': chat_id  # Return chat_id so frontend can use it
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["GET"])
def get_documents(request):
    """Get all documents for the current user"""
    try:
        # pylint: disable=no-member
        documents = Document.objects.filter(user=request.user)
        documents_data = []
        for doc in documents:
            documents_data.append({
                'id': doc.id,
                'filename': doc.filename,
                'file_type': doc.file_type,
                'file_size': doc.file_size,
                'uploaded_at': int(doc.uploaded_at.timestamp() * 1000),
                'has_text': bool(doc.extracted_text)
            })
        return JsonResponse({'documents': documents_data, 'status': 'success'})
    except Exception as e:  # pylint: disable=broad-exception-caught
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def clear_chat_documents(request):
    """Clear documents for a specific chat"""
    try:
        data = json.loads(request.body)
        chat_id = data.get('chat_id')

        if not chat_id:
            return JsonResponse({'error': 'chat_id is required'}, status=400)

        # Remove documents for this specific chat
        chat_documents = request.session.get('chat_documents', {})
        if chat_id in chat_documents:
            del chat_documents[chat_id]
            request.session['chat_documents'] = chat_documents

        return JsonResponse({'status': 'success'})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_document(request, document_id):
    """Delete a document and remove from active documents list if it was active"""
    try:
        document = get_object_or_404(Document, id=document_id, user=request.user)

        # Remove from active documents list for all chats if present
        chat_documents = request.session.get('chat_documents', {})
        for chat_id_key in list(chat_documents.keys()):
            active_documents = chat_documents[chat_id_key]
            active_documents = [d for d in active_documents if d.get('id') != document.id]
            if active_documents:
                chat_documents[chat_id_key] = active_documents
            else:
                # Remove chat entry if no documents left
                del chat_documents[chat_id_key]
        request.session['chat_documents'] = chat_documents

        # Also clear old session variables for backward compatibility
        if request.session.get('active_document_id') == document.id:
            request.session.pop('active_document_text', None)
            request.session.pop('active_document_id', None)
            request.session.pop('active_document_filename', None)
            # Also clear old active_documents for backward compatibility
            if 'active_documents' in request.session:
                request.session.pop('active_documents', None)

        document.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
