import boolean


class AND(boolean.AND):

    def __bool__(self, tags_for_check=None):
        for arg in self.args:
            if not arg.__bool__(tags_for_check):
                return False
        return True


class OR(boolean.OR):

    def __bool__(self, tags_for_check=None):
        for arg in self.args:
            if arg.__bool__(tags_for_check):
                return True
        return False


class NOT(boolean.NOT):

    def __bool__(self, tags_for_check=None):
        if self.args[0].__bool__(tags_for_check):
            return False
        return True


class Symbol(boolean.Symbol):

    def __bool__(self, tags_for_check=None):
        if self.obj in tags_for_check:
            return True
        return False


algebra = boolean.BooleanAlgebra(AND_class=AND, OR_class=OR, NOT_class=NOT, Symbol_class=Symbol)
