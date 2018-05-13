#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Allows simple creation of epub files
"""

import os
import uuid
import imghdr
import zipfile
import StringIO
import itertools
import mimetypes
import subprocess
from genshi.template import TemplateLoader

TEMPLATE_PATH = os.path.join(os.path.split(__file__)[0], "templates")

class TocMapNode:
    """
    Represents a table of contents node, 
    tables of content can take hierarchical structure. 
    """
    def __init__(self):
        """
        Set the default member variables
        """
        self.play_order = 0
        self.title = ''
        self.href = ''
        self.parent = None
        self.children = []
        self.depth = 0
        self.index = 1
    
    def assign_play_order(self):
        """
        set the order of the table of content nodes
        """
        next_play_order = [0]
        self.__assign_play_order(next_play_order)
    
    def __assign_play_order(self, next_play_order):
        """
        set the order of the table of content nodes
        """
        self.play_order = next_play_order[0]
        next_play_order[0] = self.play_order + 1
        for child in self.children:
            child.__assign_play_order(next_play_order)
    
    def get_index_str(self):
        """
        constructs a string which gives both the index and the hierarchical 
        position of the node
        """
        if self.depth <= 1:
            return str(self.index)
        elif self.parent:
            return '{0}.{1}'.format(
                self.parent.get_index_str(), str(self.index))
        else:
            raise ValueError('node has no parent')


class EpubItem:
    """
    Represents a generic item in the epub: CoverImage, chapter, etc.
    """
    def __init__(self):
        """
        Set the default values
        """
        self.id = ''
        self.dest_path = ''
        self.mime_type = ''
        self.content = ''


class EpubBook:
    """
    Represents all the information required to create an epub
    """
    def __init__(self):
        """
        Initialize the member variables
        """
        self.loader = TemplateLoader(TEMPLATE_PATH)
        
        self.uuid = uuid.uuid1()

        self.lang = 'en-US'
        self.title = ''
        self.creators = []
        self.meta_info = []

        self.image_items = {}
        self.html_items = {}
        self.css_items = {}

        self.cover_image = None
        self.title_page = None
        self.toc_page = None

        self.spine = []
        self.guide = {}
        self.toc_map_root = TocMapNode()
        self.last_node_at_depth = {0 : self.toc_map_root}
        
    def set_title(self, title):
        """
        set the epubs title
        """
        self.title = title
    
    def set_language(self, lang):
        """
        set the epubs langauge (default='en')
        """
        self.lang = lang
    
    def add_creator(self, name, role = 'aut'):
        """
        adds a creator, default role is author
        """
        self.creators.append((name, role))
        
    def add_meta(self, metaname, metavalue, **metaattrs):
        """
        add meta data to the epub
        """
        self.meta_info.append((metaname, metavalue, metaattrs))
    
    def get_meta_tags(self):
        """
        retrieve the meta data tags
        """
        tags = []
        for metaname, metavalue, metaattr in self.meta_info:
            begintag = '<dc:%s' % metaname
            if metaattr:
                for attrname, attrvalue in metaattr.iteritems():
                    begintag += ' opf:%s="%s"' % (attrname, attrvalue)
            begintag += '>'
            endtag = '</dc:%s>' % metaname
            tags.append((begintag, metavalue, endtag))
        return tags
        
    def get_image_items(self):
        """
        Retrieve all image items added to the epub
        """
        return sorted(self.image_items.values(), key = lambda x : x.id)
    
    def get_html_items(self):
        """
        Retrieve all html items added to the epub
        """
        return sorted(self.html_items.values(), key = lambda x : x.id)

    def get_css_items(self):
        """
        Retrieve all css items added to the epub
        """
        return sorted(self.css_items.values(), key = lambda x : x.id)
    
    def get_all_items(self):
        """
        Retrieve all items (image, html and css) added to the epub
        """
        return sorted(itertools.chain(
            self.image_items.values(), 
            self.html_items.values(), 
            self.css_items.values()),
            key = lambda x : x.id)
        
    def add_image(self, src, dest_path):
        """
        Add an image to the epub
        """
        item = EpubItem()
        item.id = 'image_%d' % (len(self.image_items) + 1)
        item.dest_path = dest_path
        try:
            with open(src) as _file:
                item.content = _file.read()
        except TypeError:
            item.content = src.read()
        item.mime_type = mimetypes.guess_type(dest_path)[0]
        assert item.dest_path not in self.image_items
        self.image_items[dest_path] = item
        return item
    
    def add_html_for_image(self, image_item):
        """
        Add an html image page
        """
        tmpl = self.loader.load('image.html')
        stream = tmpl.generate(book = self, item = image_item)
        html = stream.render(
            'xhtml', 
            doctype = 'xhtml11', 
            drop_xml_decl = False)
        return self.add_html('%s.html' % image_item.dest_path, html)
    
    def add_html(self, dest_path, html):
        """
        Add some html to the epub
        """
        item = EpubItem()
        item.id = 'html_%d' % (len(self.html_items) + 1)
        item.dest_path = dest_path
        item.content = html
        item.mime_type = 'application/xhtml+xml'
        assert item.dest_path not in self.html_items
        self.html_items[item.dest_path] = item
        return item
    
    def add_css(self, src, dest_path):
        """
        Add some css to the epub
        """
        item = EpubItem()
        item.id = 'css_%d' % (len(self.css_items) + 1)
        try:
            with open(src) as _file:
                item.content = _file.read()
        except TypeError:
            item.content = src.read()
        item.dest_path = dest_path
        item.mime_type = 'text/css'
        assert item.dest_path not in self.css_items
        self.css_items[item.dest_path] = item
        return item
    
    def add_cover(self, src, dest_path=None):
        """
        Add a cover image to the epub
            src
        """
        assert not self.cover_image
        if not dest_path:
            try:
                _, ext = os.path.splitext(src)
                dest_path = 'cover%s' % ext
            except AttributeError:
                dest_path = 'cover.' + imghdr.what(src)
        self.cover_image = self.add_image(src, dest_path)
        cover_page = self.add_html_for_image(self.cover_image)
        self.add_spine_item(cover_page, False, -300)
        self.add_guide_item(cover_page.dest_path, 'Cover', 'cover')
        
    def __make_title_page(self, zip_outout):
        """
        Make the title page from the template
        """
        assert self.title_page
        if self.title_page.content:
            return
        tmpl = self.loader.load('title-page.html')
        stream = tmpl.generate(book = self)
        self.title_page.content = stream.render(
            'xhtml', 
            doctype = 'xhtml11', 
            drop_xml_decl = False)
        
    def add_title_page(self, html = ''):
        """
        Add a title page to the epub
        """
        assert not self.title_page
        self.title_page = self.add_html('title-page.html', html)
        self.add_spine_item(self.title_page, True, -200)
        self.add_guide_item('title-page.html', 'Title Page', 'title-page')
    
    def __make_toc_page(self, zip_outout):
        """
        Make the table of contents page from the template
        """
        assert self.toc_page
        tmpl = self.loader.load('toc.html')
        stream = tmpl.generate(book = self)
        self.toc_page.content = stream.render(
            'xhtml', doctype = 'xhtml11', drop_xml_decl = False)

    def add_toc_page(self):
        """
        Add a table of contents page to the epub
        """
        assert not self.toc_page
        self.toc_page = self.add_html('toc.html', '')
        self.add_spine_item(self.toc_page, False, -100)
        self.add_guide_item('toc.html', 'Table of Contents', 'toc')
    
    def get_spine(self):
        """
        Retrieve the epubs spine
        """
        return sorted(self.spine)
    
    def add_spine_item(self, item, linear = True, order = None):
        """
        Add an item to the spine
        """
        assert item.dest_path in self.html_items
        if order == None:
            max_order = max(order for order, _, _ in self.spine)
            order = (max_order if self.spine else 0) + 1
        self.spine.append((order, item, linear))
    
    def get_guide(self):
        """
        get all the guide items
        """
        return sorted(self.guide.values(), key = lambda x : x[2])
    
    def add_guide_item(self, href, title, guide_type):
        """
        add a guide item
        """
        assert guide_type not in self.guide
        self.guide[guide_type] = (href, title, guide_type)
    
    def get_toc_map_root(self):
        """
        retrieve the root table of contents item
        """
        return self.toc_map_root
    
    def get_toc_map_height(self):
        """
        retrieve the depth of the table of contents
        """
        return max(self.last_node_at_depth.keys())
    
    def add_toc_map_node(self, href, title, parent = None):
        """
        Add a table of contents node
        """
        node = TocMapNode()
        node.href = href
        node.title = title
        if parent == None:
            parent = self.toc_map_root
        node.parent = parent
        parent.children.append(node)
        node.depth = parent.depth + 1
        node.index = len(parent.children)
        
        self.last_node_at_depth[node.depth] = node
        return node
    
    def __write_container_xml(self, zip_outout):
        """
        Add the container xml to the zip
        """
        tmpl = self.loader.load('container.xml')
        stream = tmpl.generate()
        zip_outout.writestr(
            os.path.join('META-INF', 'container.xml'), 
            stream.render('xml'), compress_type = zipfile.ZIP_DEFLATED)

    def __write_toc_ncx(self, zip_outout):
        """
        Add the table of contents navigation control xml to the zip
        """
        self.toc_map_root.assign_play_order()
        tmpl = self.loader.load('toc.ncx')
        stream = tmpl.generate(book = self)
        zip_outout.writestr(os.path.join('OEBPS', 'toc.ncx'), 
            stream.render('xml'), compress_type = zipfile.ZIP_DEFLATED)
    
    def __write_content_opf(self, zip_outout):
        """
        Add the content opf xml to the zip
        """
        tmpl = self.loader.load('content.opf')
        stream = tmpl.generate(book = self)
        zip_outout.writestr(os.path.join('OEBPS', 'content.opf'),
            stream.render('xml'), compress_type = zipfile.ZIP_DEFLATED)
    
    def __write_items(self, zip_outout):
        """
        Add the write all remaining items to the zip
        """
        for item in self.get_all_items():
            content = item.content
            if not item.mime_type.startswith('image'):
                content = content.encode('utf-8')
            zip_outout.writestr(
                os.path.join('OEBPS', item.dest_path), 
                content, 
                compress_type = zipfile.ZIP_DEFLATED)

    def __write_mime_type(self, zip_outout):
        """
        write the mime type to the zip
        """
        zip_outout.writestr('mimetype', 'application/epub+zip', 
            compress_type = zipfile.ZIP_STORED)
    
    def create_book(self, filename):
        """
        create the ebook
            filename: a file path or a 'file like' object
        """
        zip_outout = zipfile.ZipFile(filename, 'w')
        
        if self.title_page:
            self.__make_title_page(zip_outout)
        if self.toc_page:
            self.__make_toc_page(zip_outout)
        self.__write_mime_type(zip_outout)
        self.__write_items(zip_outout)
        self.__write_container_xml(zip_outout)
        self.__write_content_opf(zip_outout)
        self.__write_toc_ncx(zip_outout)
        
        zip_outout.close()


def test():
    """
    Perform a simple test and validate the output with epubcheck
    """
    def get_minimal_html(text):
        """
        Return some valid short html
        """
        return """<!DOCTYPE html PUBLIC "-//W3C//DTD XHtml 1.1//EN" 
        "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>%s</title></head>
<body><p>%s</p><p>Some content to the chapter.</p></body>
</html>
""" % (text, text)

    book = EpubBook()
    book.set_title('Most Wanted Tips for Aspiring Young Pirates')
    book.add_creator('Monkey D Luffy')
    book.add_creator('Guybrush Threepwood')
    book.add_meta('contributor', 'Smalltalk80', role = 'bkp')
    book.add_meta('date', '2010', event = 'publication')
    
    book.add_title_page()
    book.add_toc_page()
    image_path = os.path.join(os.path.split(__file__)[0], 
        "test-files/revenge.500x800.jpg")
    with open(image_path) as _file:
        book.add_cover(_file)
    
    #book.add_css('main.css', 'main.css')

    item1 = book.add_html('1.html', get_minimal_html('Chapter 1'))
    item11 = book.add_html('2.html', get_minimal_html('Section 1.1'))
    item111 = book.add_html('3.html', get_minimal_html('Subsection 1.1.1'))
    item12 = book.add_html('4.html', get_minimal_html('Section 1.2'))
    item2 = book.add_html('5.html', get_minimal_html('Chapter 2'))

    book.add_spine_item(item1)
    book.add_spine_item(item11)
    book.add_spine_item(item111)
    book.add_spine_item(item12)
    book.add_spine_item(item2)

    toc1 = book.add_toc_map_node(item1.dest_path, 'Chap 1')
    toc11 = book.add_toc_map_node(item11.dest_path, 'Chap 1.1', parent = toc1)
    book.add_toc_map_node(item111.dest_path, 'Chap 1.1.1', parent = toc11)
    book.add_toc_map_node(item12.dest_path, 'Chap 1.2', parent = toc1)
    book.add_toc_map_node(item2.dest_path, 'Chap 2')

    # write to disk
    stream = StringIO.StringIO()
    book.create_book(stream)
    with open('test.epub', 'w') as _file:
        _file.write(stream.getvalue())
    # check its validity
    epubcheck_path = os.path.join(os.path.split(__file__)[0], 
        "epubcheck-3.0b5/epubcheck-3.0b5.jar")
    subprocess.call(['java', '-jar', epubcheck_path, 'test.epub'])
    
if __name__ == '__main__':
    test()
