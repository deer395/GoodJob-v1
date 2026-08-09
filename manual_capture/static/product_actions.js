(function () {
  function detailDeleteControls() {
    document.querySelectorAll('dialog[id^="detail-"] article').forEach(function (article) {
      var id = article.closest('dialog').id.replace('detail-', '');
      if (article.querySelector('[data-delete-job]')) return;
      var link = document.createElement('a');
      link.href = '/jobs/' + id + '/delete';
      link.className = 'pool-link';
      link.dataset.deleteJob = id;
      link.textContent = '删除岗位';
      link.addEventListener('click', function (event) {
        event.preventDefault();
        fetch('/api/jobs/' + id + '/delete-info').then(function (response) {
          if (!response.ok) throw new Error();
          return response.json();
        }).then(function (info) {
          var dialog = document.createElement('dialog');
          var blocked = info.application_count > 0;
          dialog.innerHTML = '<form method="dialog"><button class="dialog-close">关闭</button></form>' +
            '<h2>确认删除岗位</h2><p>关联申请数量：' + info.application_count + '</p>' +
            (blocked ? '<p>为保护申请历史，该岗位不能删除。</p>' :
              '<p>删除后无法恢复该岗位记录。请确认。</p><form method="post" action="/jobs/' + id + '/delete"><input type="hidden" name="confirmed" value="true"><button type="submit">确认删除岗位</button></form>');
          document.body.appendChild(dialog); dialog.addEventListener('close', function () { dialog.remove(); }); dialog.showModal();
        }).catch(function () { window.location.href = link.href; });
      });
      article.appendChild(link);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', detailDeleteControls);
  else detailDeleteControls();
}());
