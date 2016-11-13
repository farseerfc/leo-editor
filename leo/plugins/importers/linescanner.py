#@+leo-ver=5-thin
#@+node:ekr.20161108125620.1: * @file importers/linescanner.py
#@+<< linescanner docstring >>
#@+node:ekr.20161108125805.1: ** << linescanner docstring >>
'''
#@@language rest
#@@wrap

**Overview**

Leo's import infrastructure in `leoImport.py` instantiates the
Importer instance and calls `i.run`, which calls `i.scan_lines`.

The `Importer` class replaces the horribly complex BaseScanner class.
It encapsulates *all* language-dependent knowledge.

New importers, for example, the javascript and perl importers, copy
entire lines from the input file to Leo nodes. This makes the new
importers much less error prone than the legacy
(character-by-character) importers.

New importers *nothing* about parsing. They know only about how to
scan tokens *accurately*. Again, this makes the new importers more
simple and robust than the legacy importers.

New importers are simple to write because the `Importer` class handles
complex details. Typical importer subclass will override the following methods:

- `i.run`: For complete controll of scanning.

- `i.scan_line`: Straightforward token-scanning code used by `i.v2_gen_lines`.

  If desired, `i.scan_line` can just call `i.general_scan_line`.
  
- `i.clean_headline`: Massage the definition line so it looks good in a headline.

- `initial_state`: Sets the initial state for `i.v2_gen_lines`.

**Writing a new importer**

Do the following:

1. Create a new subclass of the `Importer` class.

2. Override the `clean_headline method` and `scan_line` methods.

`scan_line` updates the net number of curly brackets and parens at the end of each line. `scan_line` must compute these numbers *accurately*, taking into account constructs such as multi-line comments, strings and regular expressions.
'''
#@-<< linescanner docstring >>
#@+<< linescanner imports >>
#@+node:ekr.20161108130715.1: ** << linescanner imports >>
import leo.core.leoGlobals as g
if g.isPython3:
    import io
    StringIO = io.StringIO
else:
    import StringIO
    StringIO = StringIO.StringIO
import re
# import time
#@-<< linescanner imports >>
#@+others
#@+node:ekr.20161108155730.1: ** class Importer
class Importer(object):
    '''
    The new, unified, simplified, interface to Leo's importer code.
    
    Unifies the old ImportController and Scanner classes.
    
    Eventually, all importers will create use this class.
    '''
    
    #@+others
    #@+node:ekr.20161108155925.1: *3* i.__init__
    #@@nobeautify

    def __init__(self,
        importCommands, 
        atAuto, # True when called from @auto logic.
        language = None, # For @language directive.
        name = None, # The kind of importer, usually the same as language
        strict = False,
    ):
        '''Importer.__init__.'''
        # Copies of args...
        self.importCommands = ic = importCommands
        self.atAuto = atAuto
        self.c = c = ic.c
        self.encoding = ic.encoding
        self.language = language or name
            # For the @language directive.
        self.name = name or language
        language = self.language
        name = self.name
        assert language and name
        assert self.language and self.name
        self.strict = strict
            # True: leading whitespace is significant.

        # Set from ivars...
        self.has_decls = name not in ('xml', 'org-mode', 'vimoutliner')
        self.is_rst = name in ('rst',)
        self.tree_type = ic.treeType # '@root', '@file', etc.
        single_delim, junk1, junk2 = g.set_delims_from_language(self.name)
        self.comment_delim = single_delim

        # Constants...
        data = g.set_delims_from_language(self.name)
        self.single_comment, self.block1, self.block2 = data
        self.escape = c.atFileCommands.underindentEscapeString
        self.escape_string = r'%s([0-9]+)\.' % re.escape(self.escape)
            # m.group(1) is the unindent value.
        self.escape_pattern = re.compile(self.escape_string)
        self.gen_refs = name in ('javascript',)
        self.gen_clean = name in ('python',)
        self.ScanState = ScanState
            # Must be set by subclasses that use general_scan_line.
        self.tab_width = c.tab_width # Also set in run()
        self.ws_pattern = re.compile(r'^\s*$|^\s*%s' % (single_delim or ''))

        # Settings...
        self.at_auto_warns_about_leading_whitespace = c.config.getBool(
            'at_auto_warns_about_leading_whitespace')
        self.warn_about_underindented_lines = True
        # self.at_auto_separate_non_def_nodes = False

        # State vars.
        ### self.context_stack = []
        self.errors = 0
        ic.errors = 0 # Required.
        self.parse_body = False
        self.ws_error = False
        self.root = None
    #@+node:ekr.20161110042512.1: *3* i.API for setting body text
    # All code in passes 1 and 2 *must* use this API to change body text.
    def add_line(self, p, s):
        '''Append the line s to p.v._import_lines.'''
        assert not p.b, repr(p.b)
        assert hasattr(p.v, '_import_lines'), repr(p)
        p.v._import_lines.append(s)

    def clear_lines(self, p):
        p.v._import_lines = []

    def extend_lines(self, p, lines):
        p.v._import_lines.extend(list(lines))

    def get_lines(self, p):
        return  p.v._import_lines
        
    def has_lines(self, p):
        return hasattr(p.v, '_import_lines')
        
    def prepend_lines(self, p, lines):
        p.v._import_lines = list(lines) + p.v._import_lines

    def set_lines(self, p, lines):
        p.v._import_lines = list(lines)
    #@+node:ekr.20161108131153.3: *3* i.check & helpers
    def check(self, unused_s, parent):
        '''ImportController.check'''
        # g.trace('='*20, self.root.h)
        trace = False # and not g.unitTesting
        trace_all = False
        trace_lines = False
        no_clean = True # True: strict lws check for *all* languages.
        sfn = g.shortFileName(self.root.h)
        s1 = g.toUnicode(self.file_s, self.encoding)
        s2 = self.trial_write()
        if self.ws_error or (not no_clean and self.gen_clean):
            s1, s2 = self.strip_lws(s1), self.strip_lws(s2)
        else:
            s1, s2 = self.clean_blank_lines(s1), self.clean_blank_lines(s2)
        # Forgive trailing whitespace problems in the last line:
        if True:
            s1, s2 = s1.rstrip()+'\n', s2.rstrip()+'\n'
        ok = s1 == s2
        if not ok and self.name == 'javascript':
            s1, s2 = self.strip_lws(s1), self.strip_lws(s2)
            ok = s1 == s2
            if ok and not g.unitTesting:
                print(
                    'indentation error: leading whitespace changed in:',
                    self.root.h)
        if not ok:
            lines1, lines2 = g.splitLines(s1), g.splitlines(s2)
            n1, n2 = len(lines1), len(lines2)
            if not g.unitTesting:
                g.es('@auto failed:', sfn, color='red')
            print('\n===== PERFECT IMPORT FAILED =====', sfn)
            print('len(s1): %s len(s2): %s' % (n1, n2))
            for i in range(min(n1, n2)):
                line1, line2 = lines1[i], lines2[i]
                if line1 != line2:
                     print('first mismatched line: %s' % (i+1))
                     print(repr(line1))
                     print(repr(line2))
                     break
            else:
                print('all common lines match')
        if trace and trace_all or (not ok and trace_lines):
            print('===== s1: %s' % parent.h)
            for i, s in enumerate(g.splitLines(s1)):
                print('%3s %r' % (i+1, s))
            g.trace('===== s2')
            for i, s in enumerate(g.splitLines(s2)):
                print('%3s %r' % (i+1, s))
        # Ensure that the unit tests fail when they should.
        # Unit tests do not generate errors unless the mismatch line does not match.
        if g.app.unitTesting:
            d = g.app.unitTestDict
            d['result'] = ok
            if not ok: d['fail'] = g.callers()
        if 0: # This is wrong headed.
            if not self.strict and not ok:
                # Suppress the error if lws is the cause.
                clean = self.strip_lws # strip_all, clean_blank_lines
                ok = clean(s1) == clean(s2)
        # g.trace('='*40, ok)
        return ok
    #@+node:ekr.20161108131153.4: *4* i.clean_blank_lines
    def clean_blank_lines(self, s):
        '''Remove all blanks and tabs in all blank lines.'''
        result = ''.join([
            z if not z.isspace() else z.replace(' ','').replace('\t','')
                for z in g.splitLines(s)
        ])
        return result
    #@+node:ekr.20161108131153.5: *4* i.strip_*
    def strip_all(self, s):
        '''Strip blank lines and leading whitespace from all lines of s.'''
        return self.strip_lws(self.strip_blank_lines(s))

    def strip_blank_lines(self, s):
        '''Strip all blank lines from s.'''
        return ''.join([z for z in g.splitLines(s) if not z.isspace()])

    def strip_lws(self, s):
        '''Strip leading whitespace from all lines of s.'''
        return ''.join([z.lstrip() for z in g.splitLines(s)])
    #@+node:ekr.20161108131153.6: *4* i.trial_write
    def trial_write(self):
        '''Return the trial write for self.root.'''
        at = self.c.atFileCommands
        if self.gen_refs:
            # Alas, the *actual* @auto write code refuses to write section references!!
            at.write(self.root,
                    nosentinels=True,           # was False,
                    perfectImportFlag=False,    # was True,
                    scriptWrite=True,           # was False,
                    thinFile=True,
                    toString=True,
                )
        else:
            at.writeOneAtAutoNode(
                self.root,
                toString=True,
                force=True,
                trialWrite=True,
            )
        return g.toUnicode(at.stringOutput, self.encoding)
    #@+node:ekr.20161108131153.7: *3* i.Overrides
    # These can be overridden in subclasses.
    #@+node:ekr.20161108131153.8: *4* i.adjust_parent
    def adjust_parent(self, parent, headline):
        '''Return the effective parent.

        This is overridden by the RstScanner class.'''
        return parent
    #@+node:ekr.20161108131153.9: *4* i.clean_headline
    def clean_headline(self, s):
        '''
        Return the cleaned version headline s.
        Will typically be overridden in subclasses.
        '''
        return s.strip()
    #@+node:ekr.20161110173058.1: *4* i.clean_nodes
    def clean_nodes(self, parent):
        '''
        Clean all nodes in parent's tree.
        Subclasses override this as desired.
        See perl_i.clean_nodes for an examplle.
        '''
        pass
    #@+node:ekr.20161108155143.6: *4* i.initial_state
    def initial_state(self):
        '''Return the initial counts.'''
        assert False, 'Importer.initial_state: to be over-ridden by subclasses.'
    #@+node:ekr.20161108170435.1: *4* i.v2_scan_line
    def v2_scan_line(self, s, prev_state):
        '''To be overridden by subclasses.'''
        assert False, 'Importer.v2_scan_line: to be over-ridden by subclasses.'
    #@+node:ekr.20161108165530.1: *3* i.Top level
    #@+node:ekr.20161112185942.1: *4* i.general_scan_line (new)
    def general_scan_line(self, s, prev_state):
        '''A generalized line scanner.'''
        trace = False and not g.unitTesting
        self.strings = ['"', "'"] # Only one-character strings.
        self.contexts = ['', '"', "'"]
        if self.block1 and self.block1 not in self.contexts:
            self.contexts.append(self.block1)
        self.context, self.curlies = prev_state.context, prev_state.curlies
        assert self.context in self.contexts, repr(self.context)
        i = 0
        while i < len(s):
            progress = i
            if self.context:
                i = self.do_ch_in_context(i, s)
            else:
                i = self.do_ch_out_of_context(i, s)
            assert progress < i
        new_state = self.ScanState(self.context, self.curlies)
        if trace: g.trace(new_state, repr(s))
        return new_state
    #@+node:ekr.20161112185942.2: *5* i.do_ch_in_context
    def do_ch_in_context(self, i, s):
        '''general_scan_line handler for when a context is in effect.'''
        match = self.match
        context = self.context
        ch = s[i]
        if ch == '\\':
            i += 2 # Eat the next character.
        elif ch == context and context in self.strings:
            self.context = '' # End the string.
            i += 1
        elif match(s, i, self.block2) and self.block1 and context == self.block1:
            self.context = '' # End the block comment.
            i += len(self.block2)
        else:
            i += 1 # Eat the character. It doesn't end the context.
        return i
    #@+node:ekr.20161112185942.3: *5* i.do_ch_out_of_context
    def do_ch_out_of_context(self, i, s):
        '''general_scan_line handler for when no context is in effect.'''
        ch = s[i]
        if ch in self.strings: # Only single-character string delims.
            self.context = ch
            i += 1
        elif self.block1 and self.match(s, i, self.block1):
            self.context = self.block1
            i += len(self.block1)
        elif self.single_comment and self.match(s, i, self.single_comment):
            i = len(s) # The single-line comment ends the line.
        elif ch == '{':
            self.curlies += 1
            i += 1
        elif ch == '}':
            self.curlies -= 1
            i += 1
        else:
            i += 1
        return i
    #@+node:ekr.20161111024447.1: *4* i.generate_nodes & helpers
    def generate_nodes(self, s, parent):
        '''
        A three-stage pipeline to generate all imported nodes.
        '''
        trace = False and not g.unitTesting
        if trace: g.trace('='*20)
            #### g.pdb()
        # Stage 1: generate nodes.
        # After this stage, the p.v._import_lines list contains p's future body text.
        self.v2_gen_lines(s, parent)
        #
        # Optional Stage 2, consisting of zero or more sub-stages.
        # Subclasses may freely override this method, **provided**
        # that all substages use the API for setting body text.
        # Changing p.b directly will cause asserts to fail in i.finish(). 
        self.post_pass(parent)
        #
        # Stage 3: Put directives in the root node and set p.b for all nodes.
        #
        # Subclasses should never need to override this stage.
        self.finish(parent)
    #@+node:ekr.20161108160409.1: *5* Stage 1: i.v2_gen_lines & helpers
    def v2_gen_lines(self, s, parent):
        '''
        Non-recursively parse all lines of s into parent, creating descendant
        nodes as needed.
        '''
        trace = False and not g.unitTesting # and self.root.h.endswith('-test.py')
        tail_p = None
        prev_state = self.initial_state()
        stack = [Target(parent, prev_state)]
        self.inject_lines_ivar(parent)
        # if trace: g.pdb('Entry: %s' % (self.root.h))
        for line in g.splitLines(s):
            # pylint doesn't understand bunches. pylint: disable=no-member
            bunch = self.scan_next_line(line, prev_state, tail_p, trace)
            new_state = bunch.new_state
            if bunch.starts_block:
                tail_p = None
                self.start_new_block(line, new_state, stack)
            elif bunch.continues_block:
                p = tail_p or stack[-1].p
                self.add_line(p, line)
            else:
                tail_p = self.end_block(line, new_state, stack)
            prev_state = new_state
    #@+node:ekr.20161110041440.1: *6* i.inject_lines_ivar
    def inject_lines_ivar(self, p):
        '''Inject _import_lines into p.v.'''
        assert not p.v._bodyString, repr(p.v._bodyString)
        p.v._import_lines = []
    #@+node:ekr.20161110070826.1: *6* i.scan_next_line
    def scan_next_line(self, line, prev_state, tail_p, trace):
        '''
        Set up the vars and trace.
        Having this be a separate method is useful while single-stepping.
        '''
        new_state = self.v2_scan_line(line, prev_state)
        starts_block = new_state.v2_starts_block(prev_state)
        continues_block = new_state.v2_continues_block(prev_state)
        if trace:
            g.trace('%s tail: %s +: %5s =: %5s %r' % (
                new_state,
                bool(tail_p),
                int(starts_block),
                int(continues_block),
                line),
            )
        return g.Bunch(
            continues_block=continues_block,
            new_state = new_state,
            starts_block = starts_block,
        )
    #@+node:ekr.20161110042847.1: *6* i.Start/end block
    #@+node:ekr.20161108160409.3: *7* i.end_block & helper
    def end_block(self, line, new_state, stack):
        # The block is ending. Add tail lines until the start of the next block.
        is_python = self.name == 'python'
        p = stack[-1].p # Put the closing line in *this* node.
        if is_python or self.gen_refs:
            tail_p = None
        else:
            tail_p = p # Put trailing lines in this node.
        if is_python:
            self.end_python_block(line, new_state, stack)
        else:
            self.add_line(p, line)
            self.cut_stack(new_state, stack)
        ### This doesn't work
        # if not self.gen_refs:
        #    tail_p = stack[-1].p
        return tail_p
    #@+node:ekr.20161108160409.4: *8* i.ends_python
    def end_python_block(self, line, new_state, stack):
        '''Handle lines at a lower level.'''
        # Unlike other languages, *this* line not only *ends*
        # a block, but *starts* a block.
        self.cut_stack(new_state, stack)
        target = stack[-1]
        h = self.clean_headline(line)
        child = self.v2_create_child_node(target.p.parent(), line, h)
        stack.pop()
            ### Is this where the line got lost?
        stack.append(Target(child, new_state))
    #@+node:ekr.20161108160409.6: *7* i.start_new_block
    def start_new_block(self, line, new_state, stack):
        '''Create a child node and update the stack.'''
        target=stack[-1]
        # Insert the reference in *this* node.
        h = self.v2_gen_ref(line, target.p, target)
        # Create a new child and associated target.
        child = self.v2_create_child_node(target.p, line, h)
        stack.append(Target(child, new_state))
    #@+node:ekr.20161110042938.1: *6* i.Utils for v2_gen_lines
    #@+node:ekr.20161108160409.2: *7* i.cut_stack
    def cut_stack(self, new_state, stack):
        '''Cut back the stack until stack[-1] matches new_state.'''
        trace = False and not g.unitTesting and self.root.h.endswith('.py')
        trace_stack = True
        if trace and trace_stack:
            print('\n'.join([repr(z) for z in stack]))
        assert stack # Fail on entry.
        while stack:
            top_state = stack[-1].state
            if new_state < top_state:
                if trace: g.trace('new_state < top_state', top_state)
                if len(stack) == 1:
                    break
                else:
                    stack.pop() 
            elif top_state == new_state:
                if trace: g.trace('new_state == top_state', top_state)
                break
            else:
                if trace: g.trace('OVERSHOOT: new_state > top_state', top_state)
                    # Can happen with valid javascript programs.
                break
        assert stack # Fail on exit.
        if trace: g.trace('new target.p:', stack[-1].p.h)
    #@+node:ekr.20161108160409.7: *7* i.v2_create_child_node
    def v2_create_child_node(self, parent, body, headline):
        '''Create a child node of parent.'''
        trace = False and not g.unitTesting and self.root.h.endswith('javascript-3.js')
        if trace: g.trace('\n\nREF: %s === in === %s\n%r\n' % (headline, parent.h, body))
        p = parent.insertAsLastChild()
        assert g.isString(body), repr(body)
        assert g.isString(headline), repr(headline)
        self.inject_lines_ivar(p)
        self.add_line(p, body)
        p.h = headline
        return p
    #@+node:ekr.20161108160409.8: *7* i.v2_gen_ref
    def v2_gen_ref(self, line, parent, target):
        '''
        Generate the ref line and a flag telling this method whether a previous
        #@+others
        #@-others
        '''
        trace = False and not g.unitTesting
        indent_ws = self.get_str_lws(line)
        h = self.clean_headline(line) 
        if self.is_rst and not self.atAuto:
            return None, None
        elif self.gen_refs:
            headline = g.angleBrackets(' %s ' % h)
            ref = '%s%s\n' % (
                indent_ws,
                g.angleBrackets(' %s ' % h))
        else:
            ref = None if target.ref_flag else '%s@others\n' % indent_ws
            target.ref_flag = True
                # Don't generate another @others in this target.
            headline = h
        if ref:
            if trace: g.trace('%s indent_ws: %r line: %r parent: %s' % (
                '*' * 20, indent_ws, line, parent.h))
            self.add_line(parent,ref)
        return headline
    #@+node:ekr.20161108131153.13: *5* Stage 2: i.post_pass & helpers
    def post_pass(self, parent):
        '''
        Optional Stage 2 of the importer pipeline, consisting of zero or more
        substages. Each substage alters nodes in various ways.
        
        Subclasses may freely override this method, **provided** that all
        substages use the API for setting body text. Changing p.b directly will
        cause asserts to fail later in i.finish().
        '''
        # g.trace('='*40)
        self.clean_all_headlines(parent)
        self.clean_all_nodes(parent)
        self.unindent_all_nodes(parent)
        #
        # This sub-pass must follow unindent_all_nodes.
        self.promote_trailing_underindented_lines(parent)
        #
        # This probably should be the last sub-pass.
        self.delete_all_empty_nodes(parent)
        
    #@+node:ekr.20161110125940.1: *6* i.clean_all_headlines
    def clean_all_headlines(self, parent):
        '''
        Clean all headlines in parent's tree by calling the language-specific
        clean_headline method.
        '''
        for p in parent.subtree():
            h = self.clean_headline(p.h)
            assert h
            if h != p.h: p.h = h
    #@+node:ekr.20161110130157.1: *6* i.clean_all_nodes
    def clean_all_nodes(self, parent):
        '''Clean the nodes in parent's tree, in a language-dependent way.'''
        # i.clean_nodes does nothing.
        # Subclasses may override as desired.
        # See perl_i.clean_nodes for an example.
        self.clean_nodes(parent)
    #@+node:ekr.20161110130709.1: *6* i.delete_all_empty_nodes (test)
    def delete_all_empty_nodes(self, parent):
        '''
        Delete nodes consisting of nothing but whitespace.
        Move the whitespace to the preceding node.
        '''
        c = self.c
        aList = []
        for p in parent.subtree():
            back = p.threadBack()
            if back != parent and not p.isCloned():
                lines = self.get_lines(p)
                # Move the whitespace from p to back.
                if all([z.isspace() for z in lines]):
                    self.extend_lines(back, lines)
                    aList.append(p.copy())
        c.deletePositionsInList(aList)
    #@+node:ekr.20161110131509.1: *6* i.promote_trailing_underindented_lines
    def promote_trailing_underindented_lines(self, parent):
        '''
        Promote all trailing underindent lines to the node's parent node,
        deleting one tab's worth of indentation. Typically, this will remove
        the underindent escape.
        '''
        pattern = self.escape_pattern # A compiled regex pattern
        for p in parent.subtree():
            lines = self.get_lines(p)
            tail = []
            while lines:
                line = lines[-1]
                m = pattern.match(line)
                if m:
                    lines.pop()
                    n_str = m.group(1)
                    try:
                        n = int(n_str)
                    except ValueError:
                        break
                    if n == abs(self.tab_width):
                        new_line = line[len(m.group(0)):]
                        tail.append(new_line)
                    else:
                        g.trace('unexpected unindent value', n)
                        break
                else:
                    break
            if tail:
                parent = p.parent()
                if parent.parent() == self.root:
                    parent = parent.parent()
                self.set_lines(p, lines)
                self.extend_lines(parent, reversed(tail))
                
    #@+node:ekr.20161110130337.1: *6* i.unindent_all_nodes (test)
    def unindent_all_nodes(self, parent):
        '''Unindent all nodes in parent's tree.'''
        for p in parent.subtree():
            lines = self.get_lines(p)
            if all([z.isspace() for z in lines]):
                # Somewhat dubious, but i.check covers for us.
                self.clear_lines(p)
            else:
                self.set_lines(p, self.undent(p))
    #@+node:ekr.20161111023249.1: *5* Stage 3: i.finish & helpers
    def finish(self, parent):
        '''
        Stage 3 (the last) stage of the importer pipeline.

        Subclasses should never need to override this method.
        '''
        # Put directives at the end, so as not to interfere with shebang lines, etc.
        self.add_root_directives(parent)
        #
        # Finally, remove all v._import_list temporaries.
        self.finalize_ivars(parent)
    #@+node:ekr.20161108160409.5: *6* i.add_root_directives
    def add_root_directives(self, parent):
        '''Return the proper directives for the root node p.'''
        table = [
            '@language %s\n' % self.language,
            '@tabwidth %d\n' % self.tab_width,
        ]
        if self.parse_body:
            pass
        else:
            self.extend_lines(parent, table)
    #@+node:ekr.20161110042020.1: *6* i.finalize_ivars
    def finalize_ivars(self, parent):
        '''
        Update the body text of all nodes in parent's tree using the injected
        v._import_lines lists.
        '''
        for p in parent.self_and_subtree():
            v = p.v
            # Make sure that no code in x.post_pass has mistakenly set p.b.
            assert not v._bodyString, repr(v._bodyString)
            v._bodyString = ''.join(v._import_lines)
            delattr(v, '_import_lines')
    #@+node:ekr.20161108131153.10: *4* i.run (entry point) & helpers
    def run(self, s, parent, parse_body=False, prepass=False):
        '''The common top-level code for all scanners.'''
        trace = False # and not g.unitTesting
        # g.trace('='*20, self.name)
        if trace: g.trace('=' * 10, parent.h)
        c = self.c
        if prepass:
            g.trace('(ImportController) Can not happen, prepass is True')
            return True, [] # Don't split any nodes.
        self.root = root = parent.copy()
        self.file_s = s
        # Init the error/status info.
        self.errors = 0
        self.parse_body = parse_body
        # Check for intermixed blanks and tabs.
        self.tab_width = c.getTabWidth(p=root)
        ws_ok = self.check_blanks_and_tabs(s) # Only issues warnings.
        # Regularize leading whitespace
        if not ws_ok:
            s = self.regularize_whitespace(s)
        # Generate the nodes, including directives and section references.
        changed = c.isChanged()
        # Completely generate all nodes.
        self.generate_nodes(s, parent)
        # Check the generated nodes.
        # Return True if the result is equivalent to the original file.
        ok = self.errors == 0 and self.check(s, parent)
        g.app.unitTestDict['result'] = ok
        # Insert an @ignore directive if there were any serious problems.
        if not ok:
            self.insert_ignore_directive(parent)
        # It's always useless for an an import to dirty the outline.
        for p in root.self_and_subtree():
            p.clearDirty()
        c.setChanged(changed)
        if trace: g.trace('-' * 10, parent.h)
        return ok
    #@+node:ekr.20161108131153.11: *5* i.check_blanks_and_tabs
    def check_blanks_and_tabs(self, lines):
        '''Check for intermixed blank & tabs.'''
        # Do a quick check for mixed leading tabs/blanks.
        trace = False and not g.unitTesting
        fn = g.shortFileName(self.root.h)
        w = self.tab_width
        blanks = tabs = 0
        for s in g.splitLines(lines):
            lws = self.get_str_lws(s)
            blanks += lws.count(' ')
            tabs += lws.count('\t')
        # Make sure whitespace matches @tabwidth directive.
        if w < 0:
            ok = tabs == 0
            message = 'tabs found with @tabwidth %s in %s' % (w, fn)
        elif w > 0:
            ok = blanks == 0
            message = 'blanks found with @tabwidth %s in %s' % (w, fn)
        if ok:
            ok = blanks == 0 or tabs == 0
            message = 'intermixed blanks and tabs in: %s' % (fn)
        if ok:
            if trace: g.trace('=====', len(lines), blanks, tabs)
        else:
            if g.unitTesting:
                self.report(message)
            else:
                g.es_print(message)
        return ok
    #@+node:ekr.20161108131153.12: *5* i.insert_ignore_directive
    def insert_ignore_directive(self, parent):
        c = self.c
        parent.b = parent.b.rstrip() + '\n@ignore\n'
        if g.unitTesting:
            g.app.unitTestDict['fail'] = g.callers()
        elif parent.isAnyAtFileNode() and not parent.isAtAutoNode():
            g.warning('inserting @ignore')
            c.import_error_nodes.append(parent.h)
    #@+node:ekr.20161108131153.14: *5* i.regularize_whitespace
    def regularize_whitespace(self, s):
        '''
        Regularize leading whitespace in s:
        Convert tabs to blanks or vice versa depending on the @tabwidth in effect.
        '''
        trace = False and not g.unitTesting
        trace_lines = False
        kind = 'tabs' if self.tab_width > 0 else 'blanks'
        kind2 = 'blanks' if self.tab_width > 0 else 'tabs'
        fn = g.shortFileName(self.root.h)
        lines = g.splitLines(s)
        count, result, tab_width = 0, [], self.tab_width
        if tab_width < 0: # Convert tabs to blanks.
            for n, line in enumerate(lines):
                i, w = g.skip_leading_ws_with_indent(line, 0, tab_width)
                s = g.computeLeadingWhitespace(w, -abs(tab_width)) + line[i:]
                    # Use negative width.
                if s != line:
                    count += 1
                    if trace and trace_lines:
                        g.es_print('%s: %r\n%s: %r' % (n+1, line, n+1, s))
                result.append(s)
        elif tab_width > 0: # Convert blanks to tabs.
            for n, line in enumerate(lines):
                s = g.optimizeLeadingWhitespace(line, abs(tab_width))
                    # Use positive width.
                if s != line:
                    count += 1
                    if trace and trace_lines:
                        g.es_print('%s: %r\n%s: %r' % (n+1, line, n+1, s))
                result.append(s)
        if count:
            self.ws_error = True # A flag to check.
            if not g.unitTesting:
                # g.es_print('Warning: Intermixed tabs and blanks in', fn)
                # g.es_print('Perfect import test will ignoring leading whitespace.')
                g.es_print('changed leading %s to %s in %s line%s in %s' % (
                    kind2, kind, count, g.plural(count), fn))
            if g.unitTesting: # Sets flag for unit tests.
                self.report('changed %s lines' % count) 
        return ''.join(result)
    #@+node:ekr.20161108131153.15: *3* i.Utils
    #@+node:ekr.20161108155143.4: *4* i.match
    def match(self, s, i, pattern):
        '''Return True if the pattern matches at s[i:]'''
        return s[i:i+len(pattern)] == pattern
    #@+node:ekr.20161108131153.18: *4* i.Messages
    def error(self, s):
        self.errors += 1
        self.importCommands.errors += 1
        if g.unitTesting:
            if self.errors == 1:
                g.app.unitTestDict['actualErrorMessage'] = s
            g.app.unitTestDict['actualErrors'] = self.errors
        else:
            g.error('Error:', s)

    def report(self, message):
        if self.strict:
            self.error(message)
        else:
            self.warning(message)

    def warning(self, s):
        if not g.unitTesting:
            g.warning('Warning:', s)
    #@+node:ekr.20161109045619.1: *4* i.print_lines
    def print_lines(self, lines):
        '''Print lines for debugging.'''
        for line in lines:
            print(repr(line))
    #@+node:ekr.20161108131153.21: *4* i.underindented_comment/line
    def underindented_comment(self, line):
        if self.at_auto_warns_about_leading_whitespace:
            self.warning(
                'underindented python comments.\n' +
                'Extra leading whitespace will be added\n' + line)

    def underindented_line(self, line):
        if self.warn_about_underindented_lines:
            self.error(
                'underindented line.\n'
                'Extra leading whitespace will be added\n' + line)
    #@+node:ekr.20161109045312.1: *3* i.Whitespace
    #@+node:ekr.20161108155143.3: *4* i.get_int_lws
    def get_int_lws(self, s):
        '''Return the the lws (a number) of line s.'''
        assert self.tab_width == self.c.tab_width, (self.tab_width, self.c.tab_width)
        return g.computeLeadingWhitespaceWidth(s, self.c.tab_width)
    #@+node:ekr.20161109053143.1: *4* i.get_leading_indent
    def get_leading_indent(self, lines, i, ignoreComments=True):
        '''
        Return the leading whitespace (an int) of the first significant line.
        Ignore blank and comment lines if ignoreComments is True
        '''
        if ignoreComments:
            while i < len(lines):
                if self.is_ws_line(lines[i]):
                    i += 1
                else:
                    break
        return self.get_int_lws(lines[i]) if i < len(lines) else 0
    #@+node:ekr.20161108131153.17: *4* i.get_str_lws
    def get_str_lws(self, s):
        '''Return the characters of the lws of s.'''
        m = re.match(r'(\s*)', s)
        return m.group(0) if m else ''
    #@+node:ekr.20161109052011.1: *4* i.is_ws_line
    def is_ws_line(self, s):
        '''Return True if s is nothing but whitespace and single-line comments.'''
        # g.trace(bool(self.ws_pattern.match(s)), repr(s))
        return bool(self.ws_pattern.match(s))
    #@+node:ekr.20161108131153.19: *4* i.undent & helper
    def undent(self, p):
        '''Remove maximal leading whitespace from the start of all lines.'''
        trace = False and not g.unitTesting # and self.root.h.endswith('.c')
        if self.is_rst:
            return p.b # Never unindent rst code.
        use_api = True
        if use_api:
            lines = self.get_lines(p)
        else:
            lines = g.splitLines(p.b)
        ws = self.common_lws(lines)
        if trace:
            g.trace('common_lws:', repr(ws))
            print('===== lines...')
            for z in lines:
                print(repr(z))
        result = []
        for s in lines:
            if s.startswith(ws):
                result.append(s[len(ws):])
            elif s.isspace():
                # Never change blank lines.
                result.append(s)
            else:
                # Indicate that the line is underindented.
                result.append("%s%s.%s" % (
                    self.c.atFileCommands.underindentEscapeString,
                    g.computeWidth(ws, self.tab_width),
                    s.lstrip()))
        if trace:
            print('----- result...')
            for z in result:
                print(repr(z))
        if use_api:
            return result
        else:
            return ''.join(result)
    #@+node:ekr.20161108131153.20: *5* i.common_lws
    def common_lws(self, lines):
        '''Return the lws (a string) common to all lines.'''
        trace = False and not g.unitTesting # and self.root.h.endswith('.c')
        if not lines:
            return ''
        lws = self.get_str_lws(lines[0])
        for s in lines:
            if not self.is_ws_line(s):
                lws2 = self.get_str_lws(s)
                if lws2.startswith(lws):
                    pass
                elif lws.startswith(lws2):
                    lws = lws2
                else:
                    lws = '' # Nothing in common.
                    break
        if trace:
            g.trace(repr(lws))
            self.print_lines(lines)
        return lws
    #@+node:ekr.20161109072221.1: *4* i.undent_body_lines & helper
    def undent_body_lines(self, lines, ignoreComments=True):
        '''
        Remove the first line's leading indentation from all lines.
        Return the resulting string.
        '''
        trace = False and not g.unitTesting
        if trace:
            g.trace('='*20)
            self.print_lines(lines)
        s = ''.join(lines)
        if self.is_rst:
            return s # Never unindent rst code.
        # Calculate the amount to be removed from each line.
        undent_val = self.get_leading_indent(lines, 0, ignoreComments=ignoreComments)
        if trace: g.trace(undent_val, repr(lines[0]))
        if undent_val == 0:
            return s
        else:
            result = self.undent_by(s, undent_val)
            if trace:
                g.trace('-'*209)
                self.print_lines(g.splitLines(result))
            return result
    #@+node:ekr.20161108180655.2: *5* i.undent_by
    def undent_by(self, s, undent_val):
        '''
        Remove leading whitespace equivalent to undent_val from each line.
        
        Strict languages: prepend the underindent escape for underindented lines.
        '''
        trace = False and not g.app.unitTesting
        if self.is_rst:
            return s # Never unindent rst code.
        result = []
        for line in g.splitlines(s):
            lws_s = self.get_str_lws(line)
            lws = g.computeWidth(lws_s, self.tab_width)
            # Add underindentEscapeString only for strict languages.
            if self.strict and not line.isspace() and lws < undent_val:
                if trace: g.trace('undent_val: %s, lws: %s, %r' % (
                    undent_val, lws, line))
                # End the underindent count with a period to
                # protect against lines that start with a digit!
                result.append("%s%s.%s" % (
                    self.escape, undent_val-lws, line.lstrip()))
            else:
                if trace: g.trace(undent_val, repr(line))
                s = g.removeLeadingWhitespace(line, undent_val, self.tab_width)
                result.append(s)
        return ''.join(result)
    #@-others
#@+node:ekr.20161108171914.1: ** class ScanState
class ScanState:
    '''A class representing the state of the scan.'''
    
    def __init__(self, context, curlies):
        '''Ctor for the ScanState class.'''
        self.context = context
        self.curlies = curlies

    def __repr__(self):
        '''ScanState.__repr__'''
        return 'ScanState context: %r curlies: %s' % (
            self.context, self.curlies)

    #@+others
    #@+node:ekr.20161108171914.2: *3* ScanState: comparisons
    def __eq__(self, other):
        '''Return True if the state continues the previous state.'''
        return self.context or self.curlies == other.curlies

    def __lt__(self, other):
        '''Return True if we should exit one or more blocks.'''
        return not self.context and self.curlies < other.curlies

    def __gt__(self, other):
        '''Return True if we should enter a new block.'''
        return not self.context and self.curlies < other.curlies

    def __ne__(self, other): return not self.__eq__(other)

    def __ge__(self, other): return self > other or self == other

    def __le__(self, other): return self < other or self == other
    #@+node:ekr.20161108171914.3: *3* ScanState: v2.starts/continues_block
    def v2_continues_block(self, prev_state):
        '''Return True if the just-scanned lines should be placed in the inner block.'''
        return self == prev_state

    def v2_starts_block(self, prev_state):
        '''Return True if the just-scanned line starts an inner block.'''
        return self > prev_state
    #@-others

#@+node:ekr.20161108155158.1: ** class Target
class Target:
    '''
    A class describing a target node p.
    state is used to cut back the stack.
    '''

    def __init__(self, p, state):
        '''Ctor for the Block class.'''
        self.p = p
        self.ref_flag = False
            # True: @others or section reference should be generated.
            # It's always True when gen_refs is True.
        self.state = state

    def __repr__(self):
        return 'Target: state: %s p: %s' % (
            self.state, g.shortFileName(self.p.h))
#@-others
#@@language python
#@@tabwidth -4
#@@pagewidth 70
#@-leo