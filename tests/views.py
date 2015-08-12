from django.views.generic.edit import CreateView
from .models import SomeModel


class SomeModelView(CreateView):
    model = SomeModel
    template_name = 'someform.html'
    success_url = '/test-url/'
