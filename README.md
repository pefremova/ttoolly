# ttoolly
Django test tools

Наборы стандартных проверок для Django-форм

### Описание тестовых классов и их параметров для описания форм

__GlobalTestMixIn__

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
|all_unique | None | не использовать | |
|choice_fields_values| {} | варианты значений для select, multiselect полей | choice_fields_values = {'field1': (value1, value2)}|
|custom_error_messages|{}| Кастомные сообщения для определенных полей| custom_error_messages = {'field1': {message_type: u"Текст сообщения об ошибке."}} |
|errors | [] | не переопределять (хранит значения ошибок для текущего теста) | |
|FILE_FIELDS| ('file', 'filename', 'image', 'preview') | названия файловых полей | |
|files | [] | список файлов в текущем тесте (используется для закрытия файлов в конце каждого теста) | f = open(filename); self.fields.append(f) |
|IMAGE_FIELDS | ('image', 'preview', 'photo') | названия полей изображений | |
|maxDiff|None| unittest.TestCase.maxDiff||
|non_field_error_key| '\__all\__' | поле, в котором возвращаются общие (не привязанные к конкретному полю) для формы ошибки ||
|unique_fields| None | список уникальных полей | unique_fields = ('field1', ('field2', 'field3'), 'field4')|


__FormTestMixIn(GlobalTestMixIn)__

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
| obj | None | модель, для котороый выполняются все проверки. Является необходимым для запуска любого теста | |
| additional_params | {} | Дополнительные параметры для всех выполняющихся в тестах запросов | additional_params = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} |
| all_fields | default_params.keys() | Список всех полей, которые должны присутствовать на форме. | all_fields = ('field1', 'field2') | 
| all_fields_add | all_fields or default_params_add.keys() | Список всех полей, которые должны присутствовать на форме создания | all_fields_add = ('field1', 'field2') |
| all_fields_edit | all_fields or default_params_edit.keys() | Список всех полей, которые должны присутствовать на форме редактирования | all_fields_edit = ('field1', 'field2') |
| choice_fields | [] | Список select полей | choice_fields = ('field1', 'field2') |
| choice_fields_add | choice_fields | Список select полей на форме создания | choice_fields_add = ('field1', 'field2') |
| choice_fields_edit | choice_fields | Список select полей на форме редактирования | choice_fields_edit = ('field1', 'field2') |
| choice_fields_with_value_in_error | [] | Список select полей, при вводе невалидного значения в которых сообщение об ошибке содержит введенное значение| choice_fields_with_value_in_error = ('field1', 'field2') |
| choice_fields_add_with_value_in_error | choice_fields_with_value_in_error |  Список select полей на странице создания, при вводе невалидного значения в которых сообщение об ошибке содержит введенное значение | choice_fields_add_with_value_in_error = ('field1', 'field2') |
| choice_fields_edit_with_value_in_error | choice_fields_with_value_in_error |  Список select полей на странице создания, при вводе невалидного значения в которых сообщение об ошибке содержит введенное значение | choice_fields_edit_with_value_in_error = ('field1', 'field2') |
| default_params | {} | Параметры по умолчанию, которые используются при создании/редактировании объекта | default_params = {'field1': value1, 'field2: value2}|
| default_params_add | default_params  | Параметры по умолчанию, которые используются при создании объекта | default_params_add = {'field1': value1, 'field2: value2}|
| default_params_edit | default_params  | Параметры по умолчанию, которые используются при редактировании объекта | default_params_edit = {'field1': value1, 'field2: value2}|
| date_fields | Ключи из default_params_add, default_params_edit, значения из all_fields_add, all_fields_edit, содержащие в названии 'date' | Названия полей, содержащих даты| date_fields = ('field1', 'field2') |
| digital_fields| None | Названия полей, содержащих числа | digital_fields = ('field1', 'field2') |
| digital_fields_add | digital_fields или default_params_add.keys(), для которых значения являются числами и не указаны в choice_fields_add, choice_fields_add_with_value_in_error | Названия полей на форме создания, содержащих числа | digital_fields_add = ('field1', 'field2')|
| digital_fields_edit | digital_fields или default_params_edit.keys(), для которых значения являются числами и не указаны в choice_fields_edit, choice_fields_edit_with_value_in_error| Названия полей на форме редактирования, содержащих числа | digital_fields_edit = ('field1', 'field2') |
| disabled_fields | None | Названия полей, выводящихся на форме, но недоступных для редактирования | disabled_fields = ('field1', 'field2') |
| disabled_fields_add | disabled_fields | Названия полей, выводящихся на форме создания, но недоступных для редактирования | disabled_fields_add = ('field1', 'field2') |
| disabled_fields_edit | disabled_fields | Названия полей, выводящихся на форме редактирования, но недоступных для редактирования | disabled_fields_edit = ('field1', 'field2') |
| email_fields | None | Названия полей для ввода email | email_fields = ('field1', 'field2') |
| email_fields_add | email_fields или ключи из default_params_add, содержащие в названии 'email' | Названия полей для ввода email на форме создания| email_fields_add = ('field1', 'field2') |
| email_fields_edit| email_fields или ключи из default_params_edit, содержащие в названии 'email' | Названия полей для ввода email на форме редактирования | email_fields_edit = ('field1', 'field2') |
| exclude_from_check | []| Названия полей, которые нужно исключить из проверки значений во всех тестах. Актуально, например, для полей, содержащих дату обновления объекта | exclude_from_check = ('field1', 'field2')|
| exclude_from_check_add |  exclude_from_check | Названия полей, которые нужно исключить из проверки значений в тестах создания объекта | exclude_from_check_add = ('field1', 'field2')|
| exclude_from_check_edit |  exclude_from_check | Названия полей, которые нужно исключить из проверки значений в тестах редактирования объекта| exclude_from_check_edit = ('field1', 'field2')|
|filter_params | None | Названия параметров для фильтрации списка объектов | filter_params = ('filter_name1', ('filter_name2', 'any_valid_value'), ) |
| hidden_fields | None | Названия полей, выводящихся на форме в скрытом виде | hidden_fields = ('field1', 'field2') |
| hidden_fields_add | hidden_fields | Названия полей, выводящихся на форме создания в скрытом виде | hidden_fields_add = ('field1', 'field2') |
| hidden_fields_edit | hidden_fields | Названия полей, выводящихся на форме редактирования в скрытом виде | hidden_fields_edit = ('field1', 'field2') |
| int_fields | None | Названия полей, содержащих целые числа | int_fields = ('field1', 'field2') |
| int_fields_add | int_fields или поля из digital_fields_add, для которых значения полей в default_params_add целочисленные | Названия полей на форме создания, содержащих целые числа | int_fields_add = ('field1', 'field2') |
| int_fields_edit | int_fields или поля из digital_fields_edit, для которых значения полей в default_params_edit целочисленные | Названия полей на форме редактирования, содержащих целые числа | int_fields_edit = ('field1', 'field2') |
| max_fields_length | [] | Список названий полей и максимальной допустимой длины значений (для текстовых) или максимального допустимого значения (для числовых) в них | max_fields_length = (('string_field_name', 100), ('digital_field_name', 99999)) |
| min_fields_length | [] | Список названий полей и минимальной допустимой длины значений (для текстовых) или минимального допустимого значения (для числовых) в них | max_fields_length = (('string_field_name', 5), ('digital_field_name', -1)) |
| multiselect_fields | None | Список multiselect полей | multiselect_fields = ('field1', 'field2') |
| multiselect_fields_add | multiselect_fields или default_params_add.keys() если значения для них являются списками | Список multiselect полей на форме создания | multiselect_fields_add = ('field1', 'field2') |
| multiselect_fields_edit | multiselect_fields или default_params_edit.keys() если значения для них являются списками  | Список multiselect полей на форме редактирования | multiselect_fields_edit = ('field1', 'field2') |
| one_of_fields | None | Список наборов полей, которые могут быть заполнены только отдельно друг от друга | one_of_fields = (('field1', 'field2'), ('field1', 'field3', 'field4')) |
| one_of_fields_add | one_of_fields | Список наборов полей, которые могут быть заполнены только отдельно друг от друга на форме создания| one_of_fields_add = (('field1', 'field2'), ('field1', 'field3', 'field4')) |
| one_of_fields_edit | one_of_fields | Список наборов полей, которые могут быть заполнены только отдельно друг от друга на форме редактирования | one_of_fields_edit = (('field1', 'field2'), ('field1', 'field3', 'field4')) |
| required_fields | None | Обязательные для заполнения поля. | required_fields = ('field1', 'field2') |
| required_fields_add | required_fields или default_params_add.keys() | Обязательные для заполнения поля на форме создания | required_fields_add = ('field1', 'field2') |
| required_fields_edit | required_fields или default_params_edit.keys() | Обязательные для заполнения поля на форме редактирования | required_fields_edit = ('field1', 'field2') |
|unique_fields_add | unique_fields (учитывается наличие в all_fields_add) | Cписок уникальных полей на форме создания | unique_fields_add = ('field1', ('field2', 'field3'), 'field4')|
|unique_fields_edit | unique_fields (учитывается наличие в all_fields_edit)| Cписок уникальных полей на форме редактирования | unique_fields_edit = ('field1', ('field2', 'field3'), 'field4')|
| url_list | | URL, на котором находится список объектов, например, в админке. Включает все тесты, связанные со списком | url_list = 'modelname:url_name' или url_list = '/path/to/list/'|
| with_captcha | Наличие поля 'captcha' в all_fields или в all_fields_add или в all_fields_edit | Используется ли капча на форме. Если True, во всех тестах отправляемые параметры дополняются полями капчи | |

__FormAddTestMixIn(FormTestMixIn)__

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
| url_add | '' | URL, по которому добавляются объекты. Включает все тесты на добавление | url_add = 'modelname:url_name_add' или url_add = '/path/to/add/'|


__FormEditTestMixIn(FormTestMixIn)__

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
| url_edit | '' | URL, по которому редактируются объекты. Включает все тесты на редактирование | url_edit = 'modelname:url_name_change' или url_edit = '/path/to/edit/1/' (в этом случае по умолчанию для редактирования будет браться объект с pk=1) |


__FormDeleteTestMixIn(FormTestMixIn)__

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
| url_delete | '' | URL, по которому удаляются объекты | url_delete = 'modelname:url_name_delete' или url_delete = '/path/to/delete/1/' |


__FormRemoveTestMixIn(FormTestMixIn)__

Тесты для объектов, удаление которых происходит в корзину

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
| url_delete | '' | URL, по которому удаляются объекты | url_delete = 'modelname:url_name_remove' или url_delete = '/path/to/remove/1/' |
| url_recovery | '' | URL, по которому выполняется восстановление объекта | url_recovery = 'modelname:url_name_recovery' или url_recovery = '/path/to/recovery/1/' |
| url_edit_in_trash | '' | URL, по которому открывается страница редактирования объекта в корзине | url_edit_in_trash = 'modelname:url_name_trash_edit' или url_edit_in_trash = '/path/to/trash/edit/1/' |


__FileTestMixIn(FormTestMixIn)__

| название поля | значение по умолчанию | описание | пример использования |
| --- | --- | --- | --- |
| file_fields_params | {} | Параметры файловых полей |file_fields_params = {'field_name': {'extensions': ('jpg', 'txt'),<br>'max_count': 3,<br>'one_max_size': '3Mb',<br>'wrong_extensions': ('rar', 'zip'),<br>'min_width': 200,<br>'min_height': 100}}|

_field_fields_params_

| название поля | описание | 
|---|---|
|extensions| разрешенные расширения |
| wrong_extensions| дополнительные невалидные расширения, которые нужно проверить в негативных тестах|
|max_count | максимальное количество файлов (для полей с множественным выбором файлов) |
|one_max_size| максимальный размер файла (одного файла для полей с множественным выбором файлов)|
|min_width| минимальная ширина изображения|
|min_height| минимальная высота изображения|


