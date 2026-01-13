"""URL configuration for chat application."""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('api/chat/', views.chat, name='chat'),
    path('api/chats/', views.get_chats, name='get_chats'),
    path('api/chats/<str:chat_id>/', views.get_chat, name='get_chat'),
    path('api/chats/<str:chat_id>/save/', views.save_chat, name='save_chat'),
    path(
        'api/chats/<str:chat_id>/delete/',
        views.delete_chat, name='delete_chat'
    ),
    path(
        'api/documents/upload/',
        views.upload_document, name='upload_document'
    ),
    path(
        'api/documents/clear-chat/',
        views.clear_chat_documents, name='clear_chat_documents'
    ),
    path('api/documents/', views.get_documents, name='get_documents'),
    path(
        'api/documents/<int:document_id>/summarize/',
        views.summarize_document, name='summarize_document'
    ),
    path(
        'api/documents/<int:document_id>/ask/',
        views.ask_document, name='ask_document'
    ),
    path(
        'api/documents/<int:document_id>/delete/',
        views.delete_document, name='delete_document'
    ),
]
