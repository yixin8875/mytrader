// 交易日志Admin JavaScript - 支持粘贴和拖拽上传图片

(function($) {
    'use strict';

    // 在文档加载完成后执行
    $(document).ready(function() {

        // 添加粘贴提示区域
        function addPasteHint() {
            const inlineGroup = $('.inline-group:last');
            if (inlineGroup.find('.paste-hint').length === 0) {
                const hint = $('<div class="paste-hint">' +
                    '<p>📋 可以粘贴剪贴板中的图片 (Ctrl+V)</p>' +
                    '<p>🖱️ 或拖拽图片到此区域上传</p>' +
                    '</div>');
                inlineGroup.prepend(hint);
            }
        }

        // 等待一小段时间确保inline group已加载
        setTimeout(addPasteHint, 500);

        // 处理粘贴事件
        $(document).on('paste', function(event) {
            const items = (event.originalEvent || event).clipboardData.items;
            const inlineGroup = $('.inline-group');

            // 检查是否在交易日志页面
            if (inlineGroup.length === 0) return;

            for (let i = 0; i < items.length; i++) {
                const item = items[i];

                // 检查是否是图片
                if (item.type.indexOf('image') !== -1) {
                    event.preventDefault();

                    const blob = item.getAsFile();
                    if (blob) {
                        uploadImage(blob);
                    }
                }
            }
        });

        // 处理拖拽事件
        $(document).on('dragover', '.paste-hint', function(e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).addClass('dragover');
        });

        $(document).on('dragleave', '.paste-hint', function(e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).removeClass('dragover');
        });

        $(document).on('drop', '.paste-hint', function(e) {
            e.preventDefault();
            e.stopPropagation();
            $(this).removeClass('dragover');

            const files = (e.originalEvent || e).dataTransfer.files;
            if (files && files.length > 0) {
                for (let i = 0; i < files.length; i++) {
                    const file = files[i];
                    if (file.type.indexOf('image') !== -1) {
                        uploadImage(file);
                    }
                }
            }
        });

        // 上传图片的函数
        function uploadImage(file) {
            // 查找最后一个inline row
            const lastRow = $('.inline-related.form-row').last();

            // 如果没有空行，点击"添加另一个"按钮
            if (lastRow.length === 0 || !lastRow.hasClass('empty-form')) {
                const addButton = $('.add-row a');
                if (addButton.length > 0) {
                    addButton.click();
                    // 等待新行添加
                    setTimeout(function() {
                        attachImageToRow($('.inline-related.form-row').last(), file);
                    }, 100);
                }
            } else {
                attachImageToRow(lastRow, file);
            }
        }

        // 将图片附加到指定行
        function attachImageToRow(row, file) {
            // 查找文件输入框
            const fileInput = row.find('input[type="file"]');

            if (fileInput.length > 0) {
                // 创建DataTransfer对象来设置文件
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);

                // 设置文件
                fileInput[0].files = dataTransfer.files;

                // 触发change事件
                fileInput.trigger('change');

                // 显示文件名
                const fileName = file.name;
                const fileLabel = $('<div class="uploaded-file-name" style="color: green; margin-top: 5px;">' +
                    '✓ 已选择: ' + fileName + '</div>');
                fileInput.parent().append(fileLabel);

                // 尝试显示预览
                if (fileInput[0].files && fileInput[0].files[0]) {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const previewImg = $('<img src="' + e.target.result + '" ' +
                            'style="max-width: 200px; max-height: 150px; margin: 10px 0; border: 1px solid #ddd; border-radius: 4px;"/>');

                        // 移除旧预览
                        fileInput.parent().find('.paste-preview').remove();

                        // 添加新预览
                        previewImg.addClass('paste-preview');
                        fileInput.parent().append(previewImg);
                    };
                    reader.readAsDataURL(file);
                }

                // 显示成功消息
                showSuccessMessage('图片 "' + file.name + '" 已添加');
            }
        }

        // 显示成功消息
        function showSuccessMessage(message) {
            const msg = $('<div class="paste-success-message" style="' +
                'position: fixed;' +
                'top: 20px;' +
                'right: 20px;' +
                'background-color: #4caf50;' +
                'color: white;' +
                'padding: 15px 20px;' +
                'border-radius: 4px;' +
                'box-shadow: 0 4px 6px rgba(0,0,0,0.1);' +
                'z-index: 9999;' +
                'animation: slideIn 0.3s ease-out;' +
                '">' + message + '</div>');

            $('body').append(msg);

            // 3秒后移除消息
            setTimeout(function() {
                msg.fadeOut(function() {
                    $(this).remove();
                });
            }, 3000);
        }

        // 监听动态添加的行
        $(document).on('click', '.add-row a', function() {
            setTimeout(function() {
                // 确保粘贴提示在正确位置
                $('.inline-group:first').find('.paste-hint').remove();
                addPasteHint();
            }, 100);
        });
    });

})(django.jQuery);
