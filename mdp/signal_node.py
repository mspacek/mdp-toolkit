import cPickle as _cPickle
import inspect as _inspect
import mdp
from mdp import numx

class NodeException(mdp.MDPException):
    """Base class for exceptions in Node subclasses."""
    pass

class TrainingException(NodeException):
    """Base class for exceptions in the training phase."""
    pass

class TrainingFinishedException(TrainingException):
    """Raised when the 'train' method is called although the
    training phase is closed."""
    pass

class IsNotTrainableException(TrainingException):
    """Raised when the 'train' method is called although the
    node is not trainable."""
    pass

class IsNotInvertibleException(NodeException):
    """Raised when the 'inverse' method is called although the
    node is not invertible."""
    pass


# methods that can overwrite docs:
DOC_METHODS = ['_train', '_stop_training', '_execute', '_inverse']

class NodeMetaclass(type):
    """This Metaclass is meant to overwrite doc strings of methods like
    execute, stop_training, inverse with the ones defined in the corresponding
    private methods _execute, _stop_training, _inverse, etc...

    This makes it possible for subclasses of Node to document the usage
    of public methods, without the need to overwrite the ancestor's methods.
    """
    
    def __new__(mcl, classname, bases, members):
        # select private methods that can overwrite the docstring
        for privname in DOC_METHODS:
            if privname in members:
                # the private method is present in the class
                # inspect the private method
                priv_info = mcl._get_infodict(members[privname])
                # if the docstring is empty, don't overwrite it
                if not priv_info['doc']:
                    continue
                # get the name of the corresponding public method
                pubname = privname[1:]
                # if public method has been overwritten in this
                # subclass, keep it
                if pubname in members:
                    continue
                # look for public method by same name in ancestors
                for base in bases:
                    ancestor = base.__dict__
                    if pubname in ancestor:
                        # we found a method by the same name in the ancestor
                        # add the class a wrapper of the ancestor public method
                        # with docs, argument defaults, and signature of the
                        # private method and name of the public method.
                        priv_info['name'] = pubname
                        members[pubname] = mcl._wrap_func(ancestor[pubname], 
                                                          priv_info)
                        break
        return type.__new__(mcl, classname, bases, members)
    
    # The next two functions (originally called get_info, wrapper)
    # are adapted versions of functions in the
    # decorator module by Michele Simionato
    # Version: 2.3.1 (25 July 2008)
    # Download page: http://pypi.python.org/pypi/decorator
    
    @staticmethod
    def _get_infodict(func):
        """
        Returns an info dictionary containing:
        - name (the name of the function : str)
        - argnames (the names of the arguments : list)
        - defaults (the values of the default arguments : tuple)
        - signature (the signature : str)
        - doc (the docstring : str)
        - module (the module name : str)
        - dict (the function __dict__ : str)
        
        >>> def f(self, x=1, y=2, *args, **kw): pass
    
        >>> info = getinfo(f)
    
        >>> info["name"]
        'f'
        >>> info["argnames"]
        ['self', 'x', 'y', 'args', 'kw']
        
        >>> info["defaults"]
        (1, 2)
    
        >>> info["signature"]
        'self, x, y, *args, **kw'
        """
        regargs, varargs, varkwargs, defaults = _inspect.getargspec(func)
        argnames = list(regargs)
        if varargs:
            argnames.append(varargs)
        if varkwargs:
            argnames.append(varkwargs)
        signature = _inspect.formatargspec(regargs,
                                           varargs,
                                           varkwargs,
                                           defaults,
                                           formatvalue=lambda value: "")[1:-1]
        return dict(name=func.__name__, argnames=argnames, signature=signature,
                    defaults = func.func_defaults, doc=func.__doc__,
                    module=func.__module__, dict=func.__dict__,
                    globals=func.func_globals, closure=func.func_closure)
    
    @staticmethod
    def _wrap_func(original_func, wrapper_infodict):
        """Return a wrapped version of func.
        
        original_func -- The function to be wrapped.
        wrapper_infodict -- The infodict to be used for constructing the
            wrapper.
        """
        src = ("lambda %(signature)s: _original_func_(%(signature)s)" %
               wrapper_infodict)
        wrapped_func = eval(src, dict(_original_func_=original_func))
        wrapped_func.__name__ = wrapper_infodict['name']
        wrapped_func.__doc__ = wrapper_infodict['doc']
        wrapped_func.__module__ = wrapper_infodict['module']
        wrapped_func.__dict__.update(wrapper_infodict['dict'])
        wrapped_func.func_defaults = wrapper_infodict['defaults']
        wrapped_func.undecorated = wrapper_infodict
        return wrapped_func


class Node(object):
    """A 'Node' is the basic building block of an MDP application.

    It represents a data processing element, like for example a learning
    algorithm, a data filter, or a visualization step.
    Each node can have one or more training phases, during which the
    internal structures are learned from training data (e.g. the weights
    of a neural network are adapted or the covariance matrix is estimated)
    and an execution phase, where new data can be processed forwards (by
    processing the data through the node) or backwards (by applying the
    inverse of the transformation computed by the node if defined).

    Nodes have been designed to be applied to arbitrarily long sets of data:
    if the underlying algorithms supports it, the internal structures can
    be updated incrementally by sending multiple batches of data (this is
    equivalent to online learning if the chunks consists of single
    observations, or to batch learning if the whole data is sent in a
    single chunk). It is thus possible to perform computations on amounts
    of data that would not fit into memory or to generate data on-the-fly.

    A 'Node' also defines some utility methods, like for example
    'copy' and 'save', that return an exact copy of a node and save it
    in a file, respectively. Additional methods may be present, depending
    on the algorithm.

    Node subclasses should take care of overwriting (if necessary)
    the functions is_trainable, _train, _stop_training, _execute,
    is_invertible, _inverse, _get_train_seq, and _get_supported_dtypes.
    If you need to overwrite the getters and setters of the
    node's properties refer to the docstring of get/set_input_dim,
    get/set_output_dim, and get/set_dtype.
    """

    __metaclass__ = NodeMetaclass

    def __init__(self, input_dim = None, output_dim = None, dtype = None):
        """If the input dimension and the output dimension are
        unspecified, they will be set when the 'train' or 'execute'
        method is called for the first time.
        If dtype is unspecified, it will be inherited from the data
        it receives at the first call of 'train' or 'execute'.

        Every subclass must take care of up- or down-casting the internal
        structures to match this argument (use _refcast private
        method when possible).
        """
        # initialize basic attributes
        self._input_dim = None
        self._output_dim = None
        self._dtype = None
        # call set functions for properties
        self.set_input_dim(input_dim)
        self.set_output_dim(output_dim)
        self.set_dtype(dtype)
 
        # skip the training phase if the node is not trainable
        if not self.is_trainable():
            self._training = False
            self._train_phase = -1
            self._train_phase_started = False
        else:
            # this var stores at which point in the training sequence we are
            self._train_phase = 0          
            # this var is False if the training of the current phase hasn't
            #  started yet, True otherwise
            self._train_phase_started = False
            # this var is False if the complete training is finished
            self._training = True

    ### properties

    def get_input_dim(self):
        """Return input dimensions."""
        return self._input_dim

    def set_input_dim(self, n):
        """Set input dimensions.
        
        Perform sanity checks and then calls self._set_input_dim(n), which
        is responsible for setting the internal attribute self._input_dim.
        Note that subclasses should overwrite self._set_input_dim
        when needed."""
        if n is None:
            pass
        elif (self._input_dim is not None) and (self._input_dim !=  n):
            msg = ("Input dim are set already (%d) "
                   "(%d given)!" % (self.input_dim, n))
            raise NodeException(msg)
        else:
            self._set_input_dim(n)

    def _set_input_dim(self, n):
        self._input_dim = n

    input_dim = property(get_input_dim,
                         set_input_dim,
                         doc = "Input dimensions")

    def get_output_dim(self):
        """Return output dimensions."""
        return self._output_dim

    def set_output_dim(self, n):
        """Set output dimensions.
        Perform sanity checks and then calls self._set_output_dim(n), which
        is responsible for setting the internal attribute self._output_dim.
        Note that subclasses should overwrite self._set_output_dim
        when needed."""
        if n is None:
            pass
        elif (self._output_dim is not None) and (self._output_dim != n):
            msg = ("Output dim are set already (%d) "
                   "(%d given)!" % (self.output_dim, n))
            raise NodeException(msg)
        else:
            self._set_output_dim(n)

    def _set_output_dim(self, n):
        self._output_dim = n

    output_dim = property(get_output_dim,
                          set_output_dim,
                          doc = "Output dimensions")

    def get_dtype(self):
        """Return dtype."""
        return self._dtype
    
    def set_dtype(self, t):
        """Set internal structures' dtype.
        Perform sanity checks and then calls self._set_dtype(n), which
        is responsible for setting the internal attribute self._dtype.
        Note that subclasses should overwrite self._set_dtype
        when needed."""
        if t is None:
            return
        t = numx.dtype(t)
        if (self._dtype is not None) and (self._dtype != t):
            errstr = ("dtype is already set to '%s' "
                      "('%s' given)!" % (t, self.dtype.name)) 
            raise NodeException(errstr)
        elif t not in self.get_supported_dtypes():
            errstr = ("\ndtype '%s' is not supported.\n"
                      "Supported dtypes: %s" % ( t.name,
                                                 [numx.dtype(t).name for t in
                                                  self.get_supported_dtypes()]))
            raise NodeException(errstr)
        else:
            self._set_dtype(t)

    def _set_dtype(self, t):
        self._dtype = t
        
    dtype = property(get_dtype,
                     set_dtype,
                     doc = "dtype")

    def _get_supported_dtypes(self):
        """Return the list of dtypes supported by this node.
        The types can be specified in any format allowed by numpy.dtype."""
        return mdp.utils.get_dtypes('All')

    def get_supported_dtypes(self):
        """Return dtypes supported by the node as a list of numpy.dtype
        objects.
        Note that subclasses should overwrite self._get_supported_dtypes
        when needed."""
        return [numx.dtype(t) for t in self._get_supported_dtypes()]

    supported_dtypes = property(get_supported_dtypes,
                                doc = "Supported dtypes")

    _train_seq = property(lambda self: self._get_train_seq(),
                          doc = "List of tuples: [(training-phase1, "
                          "stop-training-phase1), (training-phase2, "
                          "stop_training-phase2), ... ].\n"
                          " By default _train_seq = [(self._train,"
                          " self._stop_training]")

    def _get_train_seq(self):
        return [(self._train, self._stop_training)]

    ### Node states
    def is_training(self):
        """Return True if the node is in the training phase,
        False otherwise."""
        return self._training

    def get_current_train_phase(self):
        """Return the index of the current training phase. The training phases
        are defined in the list self._train_seq."""
        return self._train_phase

    def get_remaining_train_phase(self):
        """Return the number of training phases still to accomplish."""
        return len(self._train_seq) - self._train_phase

    ### Node capabilities
    def is_trainable(self):
        """Return True if the node can be trained, False otherwise."""
        return True

    def is_invertible(self):
        """Return True if the node can be inverted, False otherwise."""
        return True

    ### check functions
    def _check_input(self, x):
        # check input rank
        if not x.ndim == 2:
            error_str = "x has rank %d, should be 2" % (x.ndim)
            raise NodeException(error_str)

        # set the input dimension if necessary
        if self.input_dim is None:
            self.input_dim = x.shape[1]

        # set the dtype if necessary
        if self.dtype is None:
            self.dtype = x.dtype

        # check the input dimension
        if not x.shape[1] == self.input_dim:
            error_str = "x has dimension %d, should be %d" % (x.shape[1],
                                                              self.input_dim)
            raise NodeException(error_str)

        if x.shape[0] == 0:
            error_str = "x must have at least one observation (zero given)"
            raise NodeException(error_str)
        
    def _check_output(self, y):
        # check output rank
        if not y.ndim == 2:
            error_str = "y has rank %d, should be 2" % (y.ndim)
            raise NodeException(error_str)

        # check the output dimension
        if not y.shape[1] == self.output_dim:
            error_str = "y has dimension %d, should be %d" % (y.shape[1],
                                                              self.output_dim)
            raise NodeException(error_str)

    def _if_training_stop_training(self):
        if self.is_training():
            self.stop_training()
            # if there is some training phases left
            # we shouldn't be here!
            if self.get_remaining_train_phase() > 0:
                raise TrainingException("The training phases are not "
                                        "completed yet.")

    def _pre_execution_checks(self, x):
        """This method contains all pre-execution checks.
        It can be used when a subclass defines multiple execution methods."""

        # if training has not started yet, assume we want to train the node
        if (self.get_current_train_phase() == 0 and
            not self._train_phase_started):
            while True:
                self.train(x)
                if self.get_remaining_train_phase() > 1:
                    self.stop_training()
                else:
                    break
        
        self._if_training_stop_training()
        
        # control the dimension x
        self._check_input(x)

        # set the output dimension if necessary
        if self.output_dim is None:
            self.output_dim = self.input_dim

    def _pre_inversion_checks(self, y):
        """This method contains all pre-inversion checks.
        It can be used when a subclass defines multiple inversion methods."""
        
        if not self.is_invertible():
            raise IsNotInvertibleException("This node is not invertible.")

        self._if_training_stop_training()

        # set the output dimension if necessary
        if self.output_dim is None:
            # if the input_dim is not defined, raise an exception
            if self.input_dim is None:
                errstr = ("Number of input dimensions undefined. Inversion"
                          "not possible.")
                raise NodeException(errstr)
            self.output_dim = self.input_dim
        
        # control the dimension of y
        self._check_output(y)

    ### casting helper functions

    def _refcast(self, x):
        """Helper function to cast arrays to the internal dtype."""
        return mdp.utils.refcast(x, self.dtype)
    
    ### Methods to be implemented by the user

    # this are the methods the user has to overwrite
    # they receive the data already casted to the correct type
    
    def _train(self, x):
        if self.is_trainable():
            raise NotImplementedError

    def _stop_training(self, *args, **kwargs):
        pass

    def _execute(self, x):
        return x
        
    def _inverse(self, x):
        if self.is_invertible():
            return x

    def _check_train_args(self, x, *args, **kwargs):
        # implemented by subclasses if needed
        pass

    ### User interface to the overwritten methods
    
    def train(self, x, *args, **kwargs):
        """Update the internal structures according to the input data 'x'.
        
        'x' is a matrix having different variables on different columns
        and observations on the rows.

        By default, subclasses should overwrite _train to implement their
        training phase. The docstring of the '_train' method overwrites this
        docstring.
        """

        if not self.is_trainable():
            raise IsNotTrainableException("This node is not trainable.")

        if not self.is_training():
            raise TrainingFinishedException("The training phase has already"
            " finished.")

        self._check_input(x)
        self._check_train_args(x, *args, **kwargs)        
        
        self._train_phase_started = True
        self._train_seq[self._train_phase][0](self._refcast(x), *args, **kwargs)

    def stop_training(self, *args, **kwargs):
        """Stop the training phase.

        By default, subclasses should overwrite _stop_training to implement
        their stop-training. The docstring of the '_stop_training' method
        overwrites this docstring.
        """
        if self.is_training() and self._train_phase_started == False:
            raise TrainingException("The node has not been trained.")
        
        if not self.is_training():
            raise TrainingFinishedException("The training phase has already"
                                            "finished.")

        # close the current phase.
        self._train_seq[self._train_phase][1](*args, **kwargs)
        self._train_phase += 1
        self._train_phase_started = False
        # check if we have some training phase left
        if self.get_remaining_train_phase() == 0:
            self._training = False

    def execute(self, x, *args, **kargs):
        """Process the data contained in 'x'.
        
        If the object is still in the training phase, the function
        'stop_training' will be called.
        'x' is a matrix having different variables on different columns
        and observations on the rows.
        
        By default, subclasses should overwrite _execute to implement
        their execution phase. The docstring of the '_execute' method
        overwrites this docstring.
        """
        self._pre_execution_checks(x)
        return self._execute(self._refcast(x), *args, **kargs)

    def inverse(self, y, *args, **kargs):
        """Invert 'y'.
        
        If the node is invertible, compute the input x such that
        y = execute(x).
        
        By default, subclasses should overwrite _inverse to implement
        their inverse function. The docstring of the '_inverse' method
        overwrites this docstring.
        """
        self._pre_inversion_checks(y)
        return self._inverse(self._refcast(y), *args, **kargs)

    def __call__(self, x, *args, **kargs):
        """Calling an instance of Node is equivalent to call
        its 'execute' method."""
        return self.execute(x, *args, **kargs)

    ###### adding nodes returns flows

    def __add__(self, other):
        # check other is a node
        if isinstance(other, Node):
            return mdp.Flow([self, other])
        elif isinstance(other, mdp.Flow):
            flow_copy = other.copy()
            flow_copy.insert(0, self)
            return flow_copy.copy()
        else:
            err_str = ('can only concatenate node'
                       ' (not \'%s\') to node' % (type(other).__name__) )
            raise TypeError(err_str)
        
    ###### string representation
    
    def __str__(self):
        return str(type(self).__name__)
    
    def __repr__(self):
        # print input_dim, output_dim, dtype 
        name = type(self).__name__
        inp = "input_dim=%s" % str(self.input_dim)
        out = "output_dim=%s" % str(self.output_dim)
        if self.dtype is None:
            typ = 'dtype=None'
        else:
            typ = "dtype='%s'" % self.dtype.name
        args = ', '.join((inp, out, typ))
        return name+'('+args+')'

    def copy(self, protocol = -1):
        """Return a deep copy of the node.
        Protocol is the pickle protocol."""
        as_str = _cPickle.dumps(self, protocol)
        return _cPickle.loads(as_str)

    def save(self, filename, protocol = -1):
        """Save a pickled serialization of the node to 'filename'.
        If 'filename' is None, return a string.

        Note: the pickled Node is not guaranteed to be upward or
        backward compatible."""
        if filename is None:
            return _cPickle.dumps(self, protocol)
        else:
            # if protocol != 0 open the file in binary mode
            if protocol != 0:
                mode = 'wb'
            else:
                mode = 'w'
            flh = open(filename, mode)
            _cPickle.dump(self, flh, protocol)
            flh.close()

class Cumulator(Node):
    """A Cumulator is a Node whose training phase simply collects
    all input data. In this way it is possible to easily implement
    batch-mode learning.

    The data is accessible in the attribute 'self.data' after
    the beginning of the '_stop_training' phase. 'self.tlen' contains
    the number of data points collected.
    """

    def __init__(self, input_dim = None, output_dim = None, dtype = None):
        super(Cumulator, self).__init__(input_dim, output_dim, dtype)
        self.data = []
        self.tlen = 0

    def _train(self, x):
        """Cumulate all input data in a one dimensional list."""
        self.tlen += x.shape[0]
        self.data.extend(x.ravel().tolist())

    def _stop_training(self, *args, **kwargs):
        """Transform the data list to an array object and reshape it."""
        self.data = numx.array(self.data, dtype = self.dtype)
        self.data.shape = (self.tlen, self.input_dim)
