"""Cement core controller module."""

import textwrap
import argparse
from cement2.core import backend, exc, interface, handler

Log = backend.minimal_logger(__name__)

def controller_validator(klass, obj):
    members = [
        'setup',
        'dispatch',
        ]
    interface.validate(IController, obj, members)
    
class IController(interface.Interface):
    """
    This class defines the Controller Handler Interface.  Classes that 
    implement this handler must provide the methods and attributes defined 
    below.
    
    Implementations do *not* subclass from interfaces.
    
    """
    class imeta:
        label = 'controller'
        validator = controller_validator
    
    # Must be provided by the implementation
    meta = interface.Attribute('Handler meta-data')
    registered_controllers = interface.Attribute('List of registered controllers')
    
    def setup(base_app):
        """
        The setup function is after application initialization and after it
        is determined that this controller was requested via command line
        arguments.  Meaning, a controllers setup() function is only called
        right before it's dispatch() function is called to execute a command.
        Must 'setup' the handler object making it ready for the framework
        or the application to make further calls to it.
        
        Required Arguments:
        
            base_app
                The application object, after it has been setup() and run().
                
        Returns: n/a
        
        """
    
    def dispatch(self):
        """
        Reads the application object's data to dispatch a command from this
        controller.  For example, reading self.app.pargs to determine what
        command was passed, and then executing that command function.
                
        """

class expose(object):
    def __init__(self, hide=False, help='', aliases=[], alt=None):
        """
        Used to expose controller functions to be listed as commands, and to 
        decorate the function with meta data for the argument parser.
        
        Optional Argumnets:
        
            hide
                Whether the command should be visible
            
            help
                Help text.
            
            alias
                An alias to this command.
                
        """
        self.hide = hide
        self.help = help
        self.aliases = aliases
        
    def __call__(self, func):
        self.func = func
        self.func.label = self.func.__name__
        self.func.exposed = True
        self.func.hide = self.hide
        self.func.help = self.help
        self.func.aliases = self.aliases
        return self.func

class CementBaseController(object):
    """
    This is an implementation of the IControllerHandler interface, but as a
    base class that application controllers need to subclass from.  
    Registering it directly as a handler is useless.
    
    NOTE: This handler *requires* that the applications 'arg_handler' be
    argparse.  If using an alternative argument handler you will need to 
    write your own controller.
    
    """
    class meta:
        interface = IController
        label = None # provided in subclass
        defaults = {} # default config options
        arguments = [] # list of tuple (*args, *kwargs)
        stacked_on = None # controller name to merge commands/options into
        hide = False # whether to hide controller completely
        
    ignored = ['visible', 'hidden', 'exposed']
          
    def __init__(self):
        self.app = None
        self.command = 'default'
        self.config = None
        self.log = None
        self.pargs = None
        self.visible = {}
        self.hidden = {}
        self.exposed = {}
        self.arguments = []
        
    def setup(self, base_app):
        self.app = base_app
        self._collect()
        
        # chop off a command argument if it matches an exposed command
        if len(self.app.argv) > 0 and not self.app.argv[0].startswith('-'):
            if self.app.argv[0] in self.exposed:
                self.command = self.app.argv.pop(0)
            else:
                for label in self.exposed:
                    func = self.exposed[label]
                    if self.app.argv[0] in func['aliases']:
                        self.command = func['label']
                        self.app.argv.pop(0)
                        break
                        
        self.app.args.description = self.help_text
        self.app.args.usage = self.usage_text
        self.app.args.formatter_class=argparse.RawDescriptionHelpFormatter

        self.app._parse_args()
        
        # shortcuts
        self.config = self.app.config
        self.log = self.app.log
        self.pargs = self.app.pargs
                
    def dispatch(self):
        """
        Takes the remaining arguments from self.app.argv and parses for a
        command to dispatch, and if so... dispatches it.
        
        """
        if not self.command:
            Log.debug("no command to dispatch")
        elif self.command not in self.exposed:
            Log.debug("no function named %s" % self.command)
        else:    
            func = self.exposed[self.command]     
            Log.debug("dispatching command: %s.%s" % \
                      (func['controller'], func['label']))
            
            if func['controller'] == self.meta.label:
                getattr(self, func['label'])()
            else:
                controller = handler.get('controller', func['controller'])()
                getattr(controller, func['label'])()

    @expose(hide=True, help='default command')
    def default(self):
        raise NotImplementedError
    
    def _collect(self):
        """
        Collects all commands and arguments from this controller, and other
        availble controllers.
        """
        self.visible = {}
        self.hidden = {}
        self.exposed = {}
        self.arguments = []
    
        
        # collect our meta arguments
        Log.debug('collecting arguments from %s controller' % self.meta.label)
        for _args,_kwargs in self.meta.arguments:
            self.app.args.add_argument(_args, **_kwargs)
            
        # collect exposed commands from ourself
        Log.debug('collecting commands from %s controller' % self.meta.label)
        for member in dir(self):
            if member in self.ignored or member.startswith('_'):
                continue
                
            func = getattr(self, member)
            if hasattr(func, 'exposed'):
                func_dict = dict(
                    controller=self.meta.label,
                    label=func.label,
                    help=func.help,
                    aliases=func.aliases,
                    hide=func.hide,
                    )
                self.exposed[func.label] = func_dict
                if func.hide:
                    self.hidden[func.label] = func_dict
                else:
                    if not getattr(self.meta, 'hide', None):
                        self.visible[func.label] = func_dict
        
        # then handle stacked, and not stacked controllers
        for controller in handler.list('controller'):
            if controller.meta.label == self.meta.label:
                continue
                
            # expose other controllers as commands also (that aren't stacked
            # onto another controller)
            if not hasattr(controller.meta, 'stacked_on'):
                if getattr(controller.meta, 'label', None) == 'base':
                    continue
                    
                if not getattr(controller.meta, 'hide', None):
                    Log.debug('exposing %s controller' % controller.meta.label)
                    func_dict = dict(
                        controller=controller.meta.label,
                        label=controller.meta.label,
                        help=controller.meta.description,
                        aliases=[],
                        hide=False,
                        )
                    self.exposed[controller.meta.label] = func_dict
                    if not getattr(controller.meta, 'hide', None):
                        self.visible[controller.meta.label] = func_dict
                        
            elif controller.meta.stacked_on == self.meta.label:
                # add stacked arguments into ours
                Log.debug('collecting arguments from %s controller (stacked)' % \
                          controller.meta.label)
                for _args,_kwargs in controller.meta.arguments:
                    self.app.args.add_argument(_args, **_kwargs)
                    
                # add stacked commands into ours
                Log.debug('collecting commands from %s controller (stacked)' % \
                          controller.meta.label)
                func_dicts = controller().visible
                for label in func_dicts:
                    self.exposed[label] = func_dicts[label]
                    if func_dicts[label]['hide']:
                        self.hidden[label] = func_dicts[label]
                    else:
                        if not getattr(controller.meta, 'hide', None):
                            self.visible[label] = func_dicts[label]
               
    @property
    def usage_text(self):
        if self.meta.label == 'base':
            txt = "%s <CMD> -opt1 --opt2=VAL [arg1] [arg2] ..." % \
                self.app.args.prog
        else:
            txt = "%s %s <CMD> -opt1 --opt2=VAL [arg1] [arg2] ..." % \
                  (self.app.args.prog, self.meta.label)
        return txt
        
    @property
    def help_text(self):
        cmd_txt = ''
        for label in self.visible:
            func = self.visible[label]
            if len(func['aliases']) > 0:
                cmd_txt = cmd_txt + "  %s (aliases: %s)\n" % \
                            (func['label'], ', '.join(func['aliases']))
            else:
                cmd_txt = cmd_txt + "  %s\n" % func['label']
            
            if func['help']:
                cmd_txt = cmd_txt + "    %s\n\n" % func['help']
            else:
                cmd_txt = cmd_txt + "\n"
    
        txt = '''%s

commands:

%s

        
        ''' % (self.meta.description, cmd_txt)
        
        return textwrap.dedent(txt)        